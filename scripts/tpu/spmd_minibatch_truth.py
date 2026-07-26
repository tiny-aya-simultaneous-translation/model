"""Settle multi-host SPMD ``minibatch=True`` semantics on a real pod.

WHY THIS EXISTS
---------------
The P0 audit proved the CURRENT trainer collapses a multi-host slice to ONE
host's rows (each host ``mark_sharding``s its own batch as the *whole* global
batch; peers are discarded). The fix is the ``minibatch=True`` input pipeline:
each host feeds ``global/num_hosts`` DISTINCT rows and XLA assembles the global
sharded batch. Before wiring that into ``train_hierarchical.py`` we must know,
on real hardware, three things the docs leave ambiguous:

1. **Logical shape** the model will see — global (per_host x num_hosts) or
   per-host? This decides whether the static-shape asserts + ``batch_pad_to``
   use the global or per-host batch.
2. **Assembly + distinctness** — does host 0's gathered tensor actually contain
   all 4 hosts' distinct rows (real data parallelism), or 4x-duplicated blocks
   (no DP)?
3. Which API path works cleanly: manual ``xm.send_cpu_data_to_device`` with a
   per-rank ``ShardingSpec(minibatch=True)`` vs the dict ``MpDeviceLoader``.

Run on ALL hosts simultaneously (``--worker=all``) so the SliceBuilder mesh
forms. Each host encodes its identity into the row values
(``process_index*100 + row``) so the gather reveals assembly + distinctness.
"""

import os

os.environ.setdefault("PJRT_DEVICE", "TPU")

import torch


def _unwrap(x):
    """send_cpu_data_to_device returns an arena/list; get the tensor out."""
    while isinstance(x, (list, tuple)):
        x = x[0]
    return x


def main() -> None:
    import torch_xla
    import torch_xla.core.xla_model as xm
    import torch_xla.runtime as xr
    from torch_xla.distributed.spmd import Mesh, ShardingSpec

    xr.use_spmd()
    device = xm.xla_device()
    n_chips = xr.global_runtime_device_count()
    n_hosts = xr.process_count()
    pidx = xr.process_index()
    local = xr.addressable_runtime_device_count()
    mesh = Mesh(list(range(n_chips)), (n_chips,), ("fsdp",))
    print(f"[mb] host {pidx}/{n_hosts}: chips={n_chips} local_chips={local}", flush=True)

    per_chip = 2
    per_host = per_chip * local  # 2 x 4 = 8 on v6e-16
    assert per_host % local == 0, "divisibility guard"

    # Distinct per-host rows: column 0 = pidx*100 + row_index.
    x = torch.arange(per_host, dtype=torch.float32).reshape(per_host, 1).repeat(1, 4)
    x = x + pidx * 100.0
    print(f"[mb] host {pidx}: cpu per-host shape={tuple(x.shape)} col0={x[:, 0].tolist()}", flush=True)

    # --- Approach 1: manual send_cpu_data_to_device with a minibatch spec ---
    spec2d = ShardingSpec(mesh, ("fsdp", None), minibatch=True)
    xd = _unwrap(xm.send_cpu_data_to_device(x, device, spec2d))
    torch_xla.sync()
    logical = tuple(xd.shape)
    ann = torch_xla._XLAC._get_xla_sharding_spec(xd)
    print(f"[mb] host {pidx}: DEVICE logical shape={logical} spec={ann}", flush=True)

    # Gather the (allegedly global) tensor to CPU -- a collective; every host
    # should then see the full assembled batch.
    g = xd.cpu()
    col0 = g[:, 0].tolist()
    distinct = sorted(set(int(v) // 100 for v in col0))
    print(f"[mb] host {pidx}: GATHERED shape={tuple(g.shape)} col0={col0}", flush=True)
    print(f"[mb] host {pidx}: host-ids present in gathered batch={distinct} "
          f"(expect [0,1,2,3] => real cross-host assembly)", flush=True)

    # --- Verdict (host 0 prints the interpretation) ---
    if pidx == 0:
        is_global = logical[0] == per_host * n_hosts
        all_hosts = distinct == list(range(n_hosts))
        print("\n[mb] ===== VERDICT =====", flush=True)
        print(f"[mb] logical batch is {'GLOBAL' if is_global else 'PER-HOST'} "
              f"({logical[0]} vs per_host={per_host}, global={per_host * n_hosts})", flush=True)
        print(f"[mb] cross-host assembly + distinctness: {'YES' if all_hosts else 'NO'}", flush=True)
        print(f"[mb] => asserts/batch_pad_to must use "
              f"{'GLOBAL' if is_global else 'PER-HOST'} batch; "
              f"real data-parallelism = {all_hosts}", flush=True)


if __name__ == "__main__":
    main()
