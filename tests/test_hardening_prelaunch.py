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


def test_startup_marker_records_identity():
    # marker content is read and compared against the requested source
    assert 'head -n1 "$_marker"' in _STARTUP_SRC
    assert '[ "$_staged_src" != "$SWEEP_DATA_GS_URI" ]' in _STARTUP_SRC
    assert '[ "$_staged_src" != "hf:$HF_DATASET" ]' in _STARTUP_SRC
    # mismatch wipes the stale corpus before re-staging
    assert 'wiping stale corpus' in _STARTUP_SRC
    # identity is written INTO the marker (both branches), never a bare touch
    assert "printf '%s\\nn_pt=%s\\n' \"$SWEEP_DATA_GS_URI\"" in _STARTUP_SRC
    assert "printf 'hf:%s\\nn_pt=%s\\n' \"$HF_DATASET\"" in _STARTUP_SRC
    assert 'touch "$DATA_DIR/encoded/.unpacked"' not in _STARTUP_SRC


def test_startup_preflight_gates():
    assert 'expected-train-rows' in _STARTUP_SRC
    assert 'min-text-coverage' in _STARTUP_SRC
    # both gates refuse to launch (exit 1), not just warn
    assert _STARTUP_SRC.count('[preflight] FATAL') == 2
    # the digest rides the rendezvous ready-marker and diverging hosts refuse
    assert 'DATA_DIGEST' in _STARTUP_SRC
    assert 'dataset digests DIVERGE' in _STARTUP_SRC


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
