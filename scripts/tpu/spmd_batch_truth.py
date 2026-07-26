"""Empirically settle what the trainer's input sharding does to the batch.

WHY THIS EXISTS
---------------
The trainer moves a per-host DataLoader batch of ``train.batch_size`` rows to
the XLA device and calls ``mark_sharding(t, mesh, ("fsdp", None))`` on it
(train_hierarchical.py, device_transfer block). Under SPMD the LOGICAL tensor
shape is the global shape -- so the suspicion is that the real global batch is
``batch_size x grad_accum`` and the ``x world_size`` factor in the trainer's
``effective_batch`` banner is a DDP-era fiction (chips beyond the row count
hold GSPMD padding and contribute nothing).

This script reproduces the exact input path on a real TPU mesh and prints the
evidence:

1. **Shard map** -- the sharding annotation + per-device local shard shapes
   for a batch-4 tensor on the full ``fsdp`` mesh (v6e-8: 8 devices). If only
   4 devices hold a real row and the rest hold zero/padded shards, the batch
   is 4, not 4 x 8.
2. **Gradient equivalence** -- a tiny replicated linear layer trained one step
   on the sharded batch-4 input, versus plain CPU torch on the SAME 4 rows.
   Identical gradients prove the mesh contributes no extra data. A batch-32
   counterfactual (4 rows per chip) is included to show what the intended
   configuration would look like.

GPU analogue: none -- this is a pure GSPMD-semantics question. Run on the TPU
VM:  ``python scripts/tpu/spmd_batch_truth.py``.
"""

import os

os.environ.setdefault("PJRT_DEVICE", "TPU")

import torch


def _local_shard_shapes(t: torch.Tensor) -> list[tuple]:
    """Best-effort per-device shard shapes for a sharded XLA tensor."""
    import torch_xla

    try:
        shards = torch_xla._XLAC._get_local_shards(t)
    except Exception as e:  # noqa: BLE001 - API varies across torch_xla minors
        print(f"  (local shard introspection unavailable: {e})")
        return []
    out = []
    for shard in shards:
        # Newer torch_xla returns (tensor, index) pairs; older returns tensors.
        data = shard[0] if isinstance(shard, (tuple, list)) else shard
        out.append(tuple(data.shape))
    return out


def main() -> None:
    import torch_xla
    import torch_xla.core.xla_model as xm
    import torch_xla.distributed.spmd as xs
    import torch_xla.runtime as xr
    from torch_xla.distributed.spmd import Mesh

    xr.use_spmd()
    device = xm.xla_device()
    n = xr.global_runtime_device_count()
    mesh = Mesh(list(range(n)), (n,), ("fsdp",))
    print(f"[truth] devices={n} mesh_shape={(n,)} axis=fsdp")

    dim = 16
    torch.manual_seed(0)
    w = torch.randn(dim, 1)

    for batch in (4, 32):
        print(f"\n[truth] ===== batch_size={batch} on {n} devices =====")
        x = torch.randn(batch, dim)

        # --- exact trainer input path: .to(device) then mark_sharding
        xd = x.to(device)
        xs.mark_sharding(xd, mesh, ("fsdp", None))
        torch_xla.sync()
        print(f"[truth] logical shape       : {tuple(xd.shape)}")
        print(f"[truth] sharding annotation : {torch_xla._XLAC._get_xla_sharding_spec(xd)}")
        shard_shapes = _local_shard_shapes(xd)
        if shard_shapes:
            real = sum(1 for s in shard_shapes if s and s[0] > 0)
            print(f"[truth] local shard shapes  : {shard_shapes}")
            print(f"[truth] devices w/ real rows: {real}/{len(shard_shapes)}")

        # --- gradient equivalence vs single-device CPU on the SAME rows
        lin_x = torch.nn.Linear(dim, 1, bias=False)
        with torch.no_grad():
            lin_x.weight.copy_(w.T)
        lin_x = lin_x.to(device)
        # params replicated, exactly like the trainer's data-parallel strategy
        for p in lin_x.parameters():
            xs.mark_sharding(p, mesh, (None,) * p.dim())
        loss = lin_x(xd).mean()
        loss.backward()
        torch_xla.sync()
        grad_xla = lin_x.weight.grad.cpu()

        lin_cpu = torch.nn.Linear(dim, 1, bias=False)
        with torch.no_grad():
            lin_cpu.weight.copy_(w.T)
        lin_cpu(x).mean().backward()
        grad_cpu = lin_cpu.weight.grad

        same = torch.allclose(grad_xla, grad_cpu, rtol=1e-4, atol=1e-5)
        print(f"[truth] grad == single-device grad on the same {batch} rows: {same}")
        print(f"[truth] max |delta|: {(grad_xla - grad_cpu).abs().max().item():.3e}")
        if same:
            print(
                f"[truth] => the {n}-device mesh added NOTHING beyond the "
                f"{batch} loaded rows (real batch = batch_size, no x{n} factor)."
            )

    print(
        "\n[truth] verdict: if batch-4 grads matched CPU exactly, the trainer's "
        "effective_batch = batch_size x grad_accum x world_size overstates the "
        "real batch by x world_size."
    )


if __name__ == "__main__":
    main()
