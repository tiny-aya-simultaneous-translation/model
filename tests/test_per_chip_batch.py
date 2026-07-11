"""Tests for the per_chip_batch -> loader batch resolution (Phase 2).

WHY THIS EXISTS
---------------
The P0 audit (2026-07-12) proved the SPMD logical global batch is exactly
the loader tensor's batch dim -- the old ``effective_batch = batch x accum
x world_size`` claimed 256 while the mesh trained on 32. ``per_chip_batch``
makes the intent explicit (loader batch = per_chip x chips, single-host
only) and one normalization site feeds every downstream consumer. These
tests pin the pure resolution logic + the trainer wiring.

Run: ``python -m pytest tests/test_per_chip_batch.py -v``
"""

from __future__ import annotations

import ast
import pathlib

import pytest

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


def test_multi_host_refused():
    f = _resolve()
    with pytest.raises(ValueError, match="host"):
        f({"batch_size": 4, "per_chip_batch": 4}, n_chips=16, n_hosts=4)


def test_trainer_wiring_and_effective_batch_fix():
    # resolution happens once, before the data section
    assert "cfg[\"train\"][\"batch_size\"] = resolve_loader_batch(" in _SRC
    assert _SRC.index("resolve_loader_batch(\n") < _SRC.index("# ---- data")
    # the SPMD world multiplier is gone from effective_batch
    assert "1 if is_tpu else max(1, backend.world_size())" in _SRC
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
