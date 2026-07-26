"""Tests for WSDScheduler (warmup -> stable plateau -> linear anneal).

WHY THIS EXISTS
---------------
The v0.3 long-horizon run pairs early stopping with the schedule: a cosine
committed to the full horizon leaves every early-stopped checkpoint at a
mid-decay LR, whereas WSD holds peak LR across the plateau (any plateau
checkpoint is schedule-equivalent) and anneals only in the final window.
These tests pin the phase boundaries, the anneal-from-checkpoint recipe
(scheduler_total_steps = start_step + anneal_steps), and the trainer's
schedule selector wiring.

Run: ``python -m pytest tests/test_wsd_scheduler.py -v``
"""

from __future__ import annotations

import ast
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN_SRC = (REPO / "scripts" / "train_hierarchical.py").read_text()


class _Group(dict):
    pass


class _FakeOpt:
    """Duck-typed optimizer: schedulers only touch ``param_groups[i]['lr']``."""

    def __init__(self, lrs):
        self.param_groups = [_Group(lr=lr) for lr in lrs]


def _wsd(**kw):
    """Import the scheduler module torch-free (it never touches torch)."""
    if "torch" not in sys.modules:
        sys.modules["torch"] = MagicMock()
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sched_mod", REPO / "src" / "training" / "scheduler.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.WSDScheduler(**kw)


def test_wsd_three_phases():
    opt = _FakeOpt([1.0, 0.5])
    s = _wsd(optimizer=opt, warmup_steps=100, total_steps=1000, anneal_steps=100)
    # warmup ramp
    s.step(50)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.5)
    assert opt.param_groups[1]["lr"] == pytest.approx(0.25)  # per-group peak preserved
    # plateau: exactly peak everywhere in [warmup, anneal_start]
    for st in (100, 500, 900):
        s.step(st)
        assert opt.param_groups[0]["lr"] == pytest.approx(1.0), st
    # anneal: linear from peak to 0 over the last 100 steps
    s.step(950)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.5)
    s.step(1000)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.0)
    # past the horizon: clamped at the floor
    s.step(1100)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.0)


def test_wsd_min_lr_ratio_floor():
    opt = _FakeOpt([1.0])
    s = _wsd(
        optimizer=opt, warmup_steps=10, total_steps=100, anneal_steps=20, min_lr_ratio=0.1
    )
    s.step(100)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.1)
    s.step(90)
    assert opt.param_groups[0]["lr"] == pytest.approx(1.0 - 0.9 * (10 / 20))


def test_wsd_anneal_frac_fallback():
    opt = _FakeOpt([1.0])
    s = _wsd(optimizer=opt, warmup_steps=10, total_steps=1000, anneal_frac=0.1)
    assert s.anneal_steps == 100
    assert s.anneal_start == 900


def test_wsd_anneal_from_checkpoint_recipe():
    """Resume a plateau ckpt at step S with total = S + anneal -> anneal starts NOW."""
    opt = _FakeOpt([1.0])
    start_step = 20000
    anneal = 1500
    s = _wsd(
        optimizer=opt,
        warmup_steps=150,
        total_steps=start_step + anneal,
        anneal_steps=anneal,
    )
    assert s.anneal_start == start_step
    s.step(start_step + 1)  # the trainer's priming call on resume
    assert opt.param_groups[0]["lr"] < 1.0  # annealing immediately
    s.step(start_step + anneal)
    assert opt.param_groups[0]["lr"] == pytest.approx(0.0)


def test_wsd_anneal_never_starts_before_warmup_ends():
    opt = _FakeOpt([1.0])
    s = _wsd(optimizer=opt, warmup_steps=80, total_steps=100, anneal_steps=50)
    assert s.anneal_start == 80  # clamped to warmup end
    s.step(79)
    assert opt.param_groups[0]["lr"] == pytest.approx(79 / 80)


def test_wsd_state_dict_roundtrip():
    opt = _FakeOpt([1.0])
    s = _wsd(optimizer=opt, warmup_steps=10, total_steps=100, anneal_steps=20)
    sd = s.state_dict()
    s2 = _wsd(optimizer=_FakeOpt([1.0]), warmup_steps=1, total_steps=2, anneal_steps=1)
    s2.load_state_dict(sd)
    assert s2.anneal_start == s.anneal_start
    assert [s2.get_lr_multiplier(x) for x in (5, 50, 95)] == [
        s.get_lr_multiplier(x) for x in (5, 50, 95)
    ]


def test_trainer_schedule_selector_wired():
    assert '"schedule": "cosine"' in _TRAIN_SRC  # DEFAULTS: cosine stays default
    assert "WSDScheduler(" in _TRAIN_SRC
    assert "wsd_anneal_steps" in _TRAIN_SRC
    tree = ast.parse(_TRAIN_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
        ):
            d = ast.literal_eval(node.value)
            assert d["train"]["schedule"] == "cosine"
            assert d["train"]["wsd_anneal_frac"] == 0.1
            return
    raise AssertionError("DEFAULTS not found")
