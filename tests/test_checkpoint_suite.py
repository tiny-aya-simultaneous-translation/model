"""Tests for the public checkpoint suite: log-spaced saves + HF publisher (Phase D).

WHY THIS EXISTS
---------------
The v0.3 run keeps every checkpoint for a public mech-interp suite: log-spaced
early points {1,2,4,...,512} (Pythia convention, dense fast-dynamics sampling)
UNION save_every, and one HF ``step-N`` branch per checkpoint. These tests pin
the save-step set construction, the save condition wiring, and the publisher's
branch/step planning so the suite can't silently lose the early points.

Run: ``python -m pytest tests/test_checkpoint_suite.py -v``
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = (REPO / "scripts" / "train_hierarchical.py").read_text()
_CKPT = (REPO / "src" / "training" / "checkpointing.py").read_text()
_PUB = (REPO / "scripts" / "publish_checkpoint_suite.py").read_text()


def test_log_spaced_save_set_construction():
    # replicate the loop-setup logic and assert the Pythia early schedule
    save_at_steps = set()
    cfg_logging = {"log_spaced_saves": True, "save_at_steps": [3000, 7000]}
    save_at_steps |= {int(s) for s in (cfg_logging.get("save_at_steps") or [])}
    if cfg_logging.get("log_spaced_saves"):
        p = 1
        while p <= 512:
            save_at_steps.add(p)
            p *= 2
    assert {1, 2, 4, 8, 16, 32, 64, 128, 256, 512}.issubset(save_at_steps)
    assert {3000, 7000}.issubset(save_at_steps)  # explicit list unioned in
    assert 1024 not in save_at_steps  # cap at 512


def test_save_condition_unions_log_spaced():
    assert "(save_every and step % save_every == 0) or (step in save_at_steps)" in _TRAIN
    # DEFAULTS carries the knobs, off by default
    tree = ast.parse(_TRAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
        ):
            d = ast.literal_eval(node.value)
            assert d["logging"]["log_spaced_saves"] is False
            assert d["logging"]["save_at_steps"] is None
            return
    raise AssertionError("DEFAULTS not found")


def test_hub_push_supports_revision_and_skips_private_blobs():
    assert "revision: str | None = None" in _CKPT
    assert "api.create_branch(repo_id, branch=revision" in _CKPT
    # optimizer/scheduler/rng never leave GCS
    assert '{"optimizer.pt", "scheduler.pt", "rng.pt"}' in _CKPT


def test_publisher_plans_step_branches():
    # branch naming + weights-only + best handling are wired
    assert 'f"step-{step}"' in _PUB
    assert "revision=branch" in _PUB
    assert "--include-best" in _PUB
    # importable / parseable
    ast.parse(_PUB)


def test_async_upload_infra_and_wiring():
    # background uploader + drain, opt-in flag, periodic save uses it, final drains
    assert "def _submit_upload(fn)" in _CKPT
    assert "def wait_for_uploads(" in _CKPT
    assert "async_upload: bool = False" in _CKPT
    assert "if async_upload:" in _CKPT  # branches inline vs background
    assert "async_ckpt = bool(cfg[\"logging\"].get(\"async_checkpoint_upload\", False))" in _TRAIN
    assert "async_upload=async_ckpt" in _TRAIN  # periodic save uses it
    assert "wait_for_uploads()" in _TRAIN  # drained before final save
    # DEFAULTS carries the flag, off by default
    tree = ast.parse(_TRAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
        ):
            assert ast.literal_eval(node.value)["logging"]["async_checkpoint_upload"] is False
            return
    raise AssertionError("DEFAULTS not found")
