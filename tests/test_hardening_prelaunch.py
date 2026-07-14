"""Tests for the pre-launch hardening pass (long-horizon v6e-16 run).

WHY THIS EXISTS
---------------
The 2026-07-14 pre-launch audit found two silent failure modes (a contentless
``.unpacked`` staging marker that lets a tarball swap train on stale data, and
the zero-text alignment fallback) plus follow-on hardening: a checkpoint
integrity manifest in ``metadata.json``, a decoupled val loader batch
(``logging.val_per_chip_batch`` -- val is inference-only, so a bigger val
batch only shortens the val cycle and can never touch the LOCKED train batch
of 32), and HBM-capacity batch arithmetic for the probe matrix. These tests
pin the shell/trainer wiring and the pure-Python helpers.

Run: ``python -m pytest tests/test_hardening_prelaunch.py -v``
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = REPO / "scripts" / "train_hierarchical.py"
_TRAIN_SRC = _TRAIN.read_text()
_STARTUP_SRC = (REPO / "scripts" / "tpu" / "startup_script.sh").read_text()
_STAGE_SRC = (REPO / "scripts" / "tpu" / "stage_dataset.sh").read_text()
_PREFETCH_SRC = (REPO / "scripts" / "tpu" / "prefetch_backbones.sh").read_text()


def _resolve():
    """AST-extract resolve_loader_batch (no heavy train-script imports)."""
    tree = ast.parse(_TRAIN_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_loader_batch":
            ns: dict = {}
            exec(ast.get_source_segment(_TRAIN_SRC, node), ns)
            return ns["resolve_loader_batch"]
    raise AssertionError("resolve_loader_batch not found")


def _load_ckpt():
    """Import src/training/checkpointing.py with a stub `torch` (CPU-only CI)."""
    for name in ("torch",):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
    path = REPO / "src" / "training" / "checkpointing.py"
    spec = importlib.util.spec_from_file_location("checkpointing_hardening", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# §3.8 -- HBM capacity / val-batch arithmetic
# ---------------------------------------------------------------------------


def test_capacity_ladder_per_host_batches_v6e16():
    """b2/b4/b8 per chip on 4x4 v6e-16 -> per-host 8/16/32, all minibatch-divisible."""
    f = _resolve()
    for per_chip, per_host in ((2, 8), (4, 16), (8, 32)):
        got = f({"batch_size": 4, "per_chip_batch": per_chip}, n_chips=16, n_hosts=4)
        assert got == per_host
        # ShardingSpec(minibatch=True) guard: per-host batch % local_chips == 0
        assert got % 4 == 0


def test_val_batch_override_uses_same_resolution():
    """The val knob resolves through the SAME path as train (dict override)."""
    f = _resolve()
    train_cfg = {"batch_size": 4, "per_chip_batch": 2}
    # v6e-16: train per-host 8; val_per_chip_batch 8 -> val per-host 32.
    assert f(train_cfg, n_chips=16, n_hosts=4) == 8
    assert f({**train_cfg, "per_chip_batch": 8}, n_chips=16, n_hosts=4) == 32
    # v6e-8 single host: val per-host == global val batch.
    assert f({**train_cfg, "per_chip_batch": 8}, n_chips=8, n_hosts=1) == 64


def test_trainer_wires_val_batch_and_collator():
    """val loader must consume val_batch_size + val_collator, not train's."""
    assert 'batch_size=val_batch_size' in _TRAIN_SRC
    assert 'collate_fn=val_collator' in _TRAIN_SRC
    # knob read from logging, resolved via the train path, TPU-SPMD-only
    assert 'cfg["logging"].get("val_per_chip_batch")' in _TRAIN_SRC
    assert '"per_chip_batch": cfg["logging"]["val_per_chip_batch"]' in _TRAIN_SRC
    assert "val_per_chip_batch is TPU-SPMD-only" in _TRAIN_SRC
    # val collator pads the batch axis to the VAL batch
    assert "batch_pad_to=val_batch_size" in _TRAIN_SRC


# ---------------------------------------------------------------------------
# §2a -- checkpoint integrity manifest
# ---------------------------------------------------------------------------


def test_build_file_manifest(tmp_path):
    ckpt = _load_ckpt()
    (tmp_path / "optimizer.pt").write_bytes(b"x" * 10)
    (tmp_path / "metadata.json").write_text("{}")  # the gate: excluded
    sub = tmp_path / "peft_adapter"
    sub.mkdir()
    (sub / "adapter_model.safetensors").write_bytes(b"y" * 7)
    # a nested metadata.json (not the gate) IS manifest content
    (sub / "metadata.json").write_bytes(b"z" * 3)

    manifest = ckpt.build_file_manifest(str(tmp_path))
    assert manifest["optimizer.pt"] == 10
    assert manifest[str(pathlib.Path("peft_adapter") / "adapter_model.safetensors")] == 7
    assert manifest[str(pathlib.Path("peft_adapter") / "metadata.json")] == 3
    assert "metadata.json" not in manifest


def test_save_checkpoint_stamps_manifest():
    """save_checkpoint must build the manifest into metadata (source wiring)."""
    src = (REPO / "src" / "training" / "checkpointing.py").read_text()
    assert 'meta["files"] = build_file_manifest(write_dir)' in src


# ---------------------------------------------------------------------------
# §3.1/§3.2/§3.3 -- startup staging identity, preflight, HF offline
# ---------------------------------------------------------------------------


def test_stage_marker_records_identity():
    # marker content is read and compared against the requested source
    assert 'head -n1 "$_marker"' in _STAGE_SRC
    assert '[ "$_staged_src" != "$SWEEP_DATA_GS_URI" ]' in _STAGE_SRC
    assert '[ "$_staged_src" != "hf:$HF_DATASET" ]' in _STAGE_SRC
    # mismatch wipes the stale corpus before re-staging
    assert 'wiping stale corpus' in _STAGE_SRC
    # identity is written INTO the marker (both branches), never a bare touch
    assert "printf '%s\\nn_pt=%s\\n' \"$SWEEP_DATA_GS_URI\"" in _STAGE_SRC
    assert "printf 'hf:%s\\nn_pt=%s\\n' \"$HF_DATASET\"" in _STAGE_SRC
    assert 'touch "$DATA_DIR/encoded/.unpacked"' not in _STAGE_SRC


def test_stage_preflight_gates():
    # gates are env-driven (startup passes the metadata values through)
    assert 'EXPECTED_TRAIN_ROWS="${EXPECTED_TRAIN_ROWS:-0}"' in _STAGE_SRC
    assert 'MIN_TEXT_COVERAGE="${MIN_TEXT_COVERAGE:-0}"' in _STAGE_SRC
    # both gates refuse to launch (exit 1), not just warn
    assert _STAGE_SRC.count('[preflight] FATAL') == 2
    # digest written for the rendezvous marker
    assert '.data_digest' in _STAGE_SRC


def test_startup_delegates_staging_and_rides_digest():
    # startup calls the extracted script with the metadata gates...
    assert 'bash "$REPO_DIR/scripts/tpu/stage_dataset.sh"' in _STARTUP_SRC
    assert 'read_meta expected-train-rows 0' in _STARTUP_SRC
    assert 'read_meta min-text-coverage 0' in _STARTUP_SRC
    # ...reads the digest and refuses to launch on divergence
    assert '.data_digest' in _STARTUP_SRC
    assert 'DATA_DIGEST' in _STARTUP_SRC
    assert 'dataset digests DIVERGE' in _STARTUP_SRC
    # the old inline staging is gone (single source of truth)
    assert 'tar -xzf /tmp/sweep_subset.tar.gz' not in _STARTUP_SRC


# ---------------------------------------------------------------------------
# per-host TPU telemetry (all 16 chips via 4 labeled host streams)
# ---------------------------------------------------------------------------


def test_tpu_info_hbm_table_parser():
    """Parse both live tpu-info cell formats; skip headers and N/A rows."""
    import importlib.util as _ilu

    # real torch (in the venv) -- evict a MagicMock left by _load_ckpt() in the
    # same pytest session; stub only the TPU-only torch_xla family, and REMOVE
    # the stubs afterwards (leaked mocks make later tests believe torch_xla is
    # importable and flip their backend dispatch).
    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
    _injected = []
    for name in ("torch_xla", "torch_xla.core", "torch_xla.core.xla_model",
                 "torch_xla.runtime", "torch_xla.distributed",
                 "torch_xla.distributed.spmd"):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
            _injected.append(name)
    try:
        path = REPO / "src" / "backend" / "tpu_backend.py"
        spec = _ilu.spec_from_file_location("tpu_backend_hardening", path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parse = mod.TPUBackend._parse_tpu_info_hbm_table
    finally:
        for name in _injected:
            sys.modules.pop(name, None)

    live_format = """TPU HBM Usage
| Device | HBM Usage (GiB)       |
|--------|-----------------------|
| 8      | 27.19 GiB / 31.25 GiB |
| 9      | 27.19 GiB / 31.25 GiB |
| 12     | 25.56 GiB / 31.25 GiB |
| 13     | N/A             |
"""
    rows = parse(live_format)
    assert rows == [(8, 27.19, 31.25), (9, 27.19, 31.25), (12, 25.56, 31.25)]
    # newer bare-number cells (unit in the header)
    assert parse("| 0 | 12.34 |") == [(0, 12.34, 31.246)]
    assert parse("garbage\nno table") == []


def test_trainer_logs_per_host_tpu_telemetry():
    # every host logs (not is_main-gated): the block checks wandb.run directly
    assert 'tpu_telemetry_every' in _TRAIN_SRC
    assert 'f"tpu/host{_hidx}/chip{_cid}_hbm_gib"' in _TRAIN_SRC
    assert 'hasattr(backend, "hbm_per_chip")' in _TRAIN_SRC
    # default off; production configs opt in
    assert '"tpu_telemetry_every": 0,' in _TRAIN_SRC
    for cfgname in ("stage2_tpu_v6e16_full_v03_mh.yaml", "stage2_tpu_v6e16_full_v03_mh_anneal.yaml"):
        assert "tpu_telemetry_every: 250" in (REPO / "configs" / "tpu" / cfgname).read_text()


# ---------------------------------------------------------------------------
# public-release metrics (Tier A/B/C)
# ---------------------------------------------------------------------------


def _extract_fn(name):
    """AST-extract a module-level function from the train script."""
    tree = ast.parse(_TRAIN_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            import torch  # real torch: the helper does tensor math

            ns: dict = {"torch": torch}
            exec(ast.get_source_segment(_TRAIN_SRC, node), ns)
            return ns[name]
    raise AssertionError(f"{name} not found")


def test_codebook_entropy_stats():
    import torch

    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
        import torch  # noqa: F811 - re-import the real one

    f = _extract_fn("_codebook_entropy_stats")
    V = 2048
    hist = torch.zeros(3, V)
    hist[0] = 1.0                # uniform -> max entropy = log2(2048) = 11 bits
    hist[1, 7] = 100.0           # one-hot -> 0 bits, active 1/V
    #      hist[2] stays empty  -> zeros
    ent, act = f(hist)
    assert abs(ent[0] - 11.0) < 1e-6 and abs(act[0] - 1.0) < 1e-9
    assert ent[1] == 0.0 and abs(act[1] - 1.0 / V) < 1e-9
    assert ent[2] == 0.0 and act[2] == 0.0


def test_release_metric_wiring():
    # Tier A: counters + sys + ppl + trust-region ratio
    assert '"train/tokens_seen": float(step) * frame_tokens_per_step' in _TRAIN_SRC
    assert '"train/samples_seen": float(step) * effective_batch' in _TRAIN_SRC
    assert '"train/epoch"' in _TRAIN_SRC
    assert '"sys/resumes": _resume_count' in _TRAIN_SRC
    assert '"resumes": _resume_count' in _TRAIN_SRC  # persisted in extra_state
    assert 'sys/boot_to_first_log_sec' in _TRAIN_SRC
    assert '"val/text_ppl": math.exp(min(_vt, 30.0))' in _TRAIN_SRC
    assert 'f"opt/update_weight_ratio/{gname}"' in _TRAIN_SRC
    # provenance
    assert '"provenance/git_sha": _resolve_build_sha()' in _TRAIN_SRC
    assert '"provenance/data_digest": _read_data_digest(cfg)' in _TRAIN_SRC
    # Tier B: codebook histogram + exploded list keys
    assert '_codebook_entropy_stats(' in _TRAIN_SRC
    assert '"val/per_codebook_entropy_bits"' in _TRAIN_SRC
    assert 'f"val/per_codebook_active_frac_{i}"' in _TRAIN_SRC
    # Tier C: MFU + PF-days + checkpoint index
    assert 'perf/mfu_est' in _TRAIN_SRC
    assert 'perf/cum_pf_days_est' in _TRAIN_SRC
    assert '"checkpoints/index": wandb.Table(' in _TRAIN_SRC
    # define_metric families
    for fam in ("sys/*", "opt/*", "checkpoints/*", "eval/*"):
        assert f'wandb.define_metric("{fam}", step_metric="global_step")' in _TRAIN_SRC
    # shared-mode bug fix: telemetry rides global_step, never step=
    _tel = _TRAIN_SRC.split("Host-level stats ride along")[1][:1600]
    assert '"global_step": step' in _tel
    assert "_wtel.log(_tel)" in _TRAIN_SRC and "_wtel.log(_tel, step=" not in _TRAIN_SRC


def test_tpu_audio_demo_wiring():
    # static-shape generator exists and never slices with python ints at the
    # frontier (index_select/scatter with runtime index tensors instead)
    assert "def generate_audio_sample_tpu(" in _TRAIN_SRC
    gen_src = _TRAIN_SRC.split("def generate_audio_sample_tpu(")[1].split("\ndef ")[0]
    assert "index_select" in gen_src and ".scatter(" in gen_src
    assert "backend.sync()" in gen_src
    # ALL hosts enter on TPU (no is_main gate on the call), GPU path intact
    assert "if _audio_due and is_tpu:" in _TRAIN_SRC
    assert "generate_audio_sample_tpu(" in _TRAIN_SRC
    assert '"audio_ar_frames": 50,' in _TRAIN_SRC
    # BUILD_SHA stamped into deploy tarballs
    hot = (REPO / "scripts" / "tpu" / "hot_redeploy.sh").read_text()
    assert "git rev-parse HEAD > BUILD_SHA" in hot and "BUILD_SHA" in hot.split("-czf")[1]


def test_startup_hf_offline_gated_on_prefetch():
    # marker written only by prefetch verification...
    assert 'touch /tmp/hf_backbones_ready' in _PREFETCH_SRC
    assert 'rm -f /tmp/hf_backbones_ready' in _PREFETCH_SRC
    # ...and consumed by BOTH tmux launch branches
    assert '[ -f /tmp/hf_backbones_ready ] && _HF_OFFLINE=1' in _STARTUP_SRC
    assert _STARTUP_SRC.count("HF_HUB_OFFLINE='$_HF_OFFLINE'") == 2


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
