"""Tests for the per_chip_batch -> loader batch resolution (Phase 2).

WHY THIS EXISTS
---------------
The P0 audit (2026-07-12) proved the SPMD logical global batch is exactly
the loader tensor's batch dim -- the old ``effective_batch = batch x accum
x world_size`` claimed 256 while the mesh trained on 32. ``per_chip_batch``
makes the intent explicit and one normalization site feeds every downstream
consumer. resolve_loader_batch returns the PER-HOST batch (per_chip x
local_chips); single-host local_chips == n_chips (unchanged), multi-host
local_chips == n_chips // n_hosts and the minibatch pipeline assembles the
global batch across hosts. These tests pin the resolution + trainer wiring.

Run: ``python -m pytest tests/test_per_chip_batch.py -v``
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = REPO / "scripts" / "train_hierarchical.py"
_SRC = _TRAIN.read_text()


def _resolve():
    """AST-extract resolve_loader_batch (no heavy train-script imports)."""
    tree = ast.parse(_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_loader_batch":
            ns: dict = {}
            exec(ast.get_source_segment(_SRC, node), ns)
            return ns["resolve_loader_batch"]
    raise AssertionError("resolve_loader_batch not found")


def test_unset_keeps_legacy_batch_size():
    f = _resolve()
    assert f({"batch_size": 4, "per_chip_batch": None}, n_chips=8, n_hosts=1) == 4
    assert f({"batch_size": 4}, n_chips=8, n_hosts=1) == 4


def test_per_chip_times_chips_single_host():
    f = _resolve()
    assert f({"batch_size": 4, "per_chip_batch": 4}, n_chips=8, n_hosts=1) == 32
    assert f({"batch_size": 1, "per_chip_batch": 2}, n_chips=8, n_hosts=1) == 16


def test_multi_host_returns_per_host_batch():
    """Multi-host now RESOLVES (no longer refuses): per_chip x local_chips.

    v6e-16: per_chip 2, n_chips 16, n_hosts 4 -> local_chips 4 -> per-host 8.
    The minibatch pipeline assembles per_host(8) x host_count(4) = global 32.
    """
    f = _resolve()
    assert f({"batch_size": 4, "per_chip_batch": 2}, n_chips=16, n_hosts=4) == 8
    # per-host batch must be divisible by local_chips for the minibatch guard
    assert (f({"batch_size": 4, "per_chip_batch": 2}, n_chips=16, n_hosts=4) % 4) == 0
    # single-host unchanged (local_chips == n_chips)
    assert f({"batch_size": 4, "per_chip_batch": 2}, n_chips=8, n_hosts=1) == 16


def test_trainer_wiring_and_effective_batch_fix():
    # resolution happens once, before the data section
    assert "cfg[\"train\"][\"batch_size\"] = resolve_loader_batch(" in _SRC
    assert _SRC.index("resolve_loader_batch(\n") < _SRC.index("# ---- data")
    # effective_batch multiplies by host_count on TPU (1 single-host, 4 multi-host)
    assert "n_hosts if is_tpu else max(1, backend.world_size())" in _SRC
    # multi-host gate + minibatch primitive are wired
    assert "multihost = is_tpu_early and n_hosts > 1" in _SRC
    assert "backend.shard_to_device(" in _SRC
    # banner shows the true global batch
    assert "global_batch={effective_batch}" in _SRC
    # DEFAULTS carries the knob, off by default
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
        ):
            assert ast.literal_eval(node.value)["train"]["per_chip_batch"] is None
            return
    raise AssertionError("DEFAULTS not found")
