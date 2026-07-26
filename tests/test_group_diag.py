"""Tests for the per-group stability telemetry + the clip-key normalization.

Covers two 2026-07-10 changes in scripts/train_hierarchical.py:

1. ``load_config`` honors ``train.clip_grad_norm`` (the spelling every TPU
   YAML uses) by copying it over ``train.max_grad_norm`` — the key the clip
   sites actually read. Regression test for the dead-key incident where the
   clip-10 probes silently ran at the 1.0 default.

2. ``_group_grad_diag`` per-group reductions and the host-side RMS math:
   ``weight_rms == sqrt(mean(p^2))`` and ``update_rms_est == lr * grad_rms``.

Functions are AST-extracted from the train script (pattern from
test_sweep_capacity_knobs) so the test never imports its heavy top-level deps
(peft/transformers/torch_xla) and stays robust to torch import-state pollution
from sibling tests.
"""

from __future__ import annotations

import ast
import math
import pathlib
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = "scripts/train_hierarchical.py"


def _extract_source(filename: str, name: str) -> str:
    """Source of one top-level function/class/assignment by name."""
    src = (REPO / filename).read_text()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return ast.get_source_segment(src, node)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.get_source_segment(src, node)
    raise AssertionError(f"{name} not found in {filename}")


# ---- load_config: clip_grad_norm -> max_grad_norm normalization ------------


def _load_config_fn():
    yaml = pytest.importorskip("yaml")
    ns: dict = {"json": __import__("json"), "yaml": yaml}
    exec(_extract_source(_TRAIN, "DEFAULTS"), ns)
    exec(_extract_source(_TRAIN, "_deep_update"), ns)
    exec(_extract_source(_TRAIN, "load_config"), ns)
    return ns["load_config"]


def test_clip_grad_norm_yaml_key_is_honored(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        textwrap.dedent(
            """
            train:
              enable_clip_grad_norm: true
              clip_grad_norm: 10.0
            """
        )
    )
    cfg = _load_config_fn()(str(cfg_path), {})
    assert cfg["train"]["max_grad_norm"] == 10.0


def test_max_grad_norm_defaults_to_one(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text("train:\n  batch_size: 2\n")
    cfg = _load_config_fn()(str(cfg_path), {})
    assert cfg["train"]["max_grad_norm"] == 1.0


def test_max_grad_norm_spelling_still_works(tmp_path):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text("train:\n  max_grad_norm: 5.0\n")
    cfg = _load_config_fn()(str(cfg_path), {})
    assert cfg["train"]["max_grad_norm"] == 5.0


def test_scheduler_horizon_and_seed_defaults(tmp_path):
    # scheduler_total_steps decouples cosine horizon from run length (round-2
    # probe requirement); seed drives torch RNG + bucket-sampler data order.
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text("train:\n  max_steps: 1500\n  scheduler_total_steps: 5000\n")
    cfg = _load_config_fn()(str(cfg_path), {})
    assert int(cfg["train"]["scheduler_total_steps"] or cfg["train"]["max_steps"]) == 5000
    assert cfg["train"]["seed"] == 42  # default preserves v0.3-arm comparability

    cfg_path.write_text("train:\n  max_steps: 1500\n")
    cfg = _load_config_fn()(str(cfg_path), {})
    assert int(cfg["train"].get("scheduler_total_steps") or cfg["train"]["max_steps"]) == 1500


# ---- _group_grad_diag: per-group reductions + host RMS derivation ----------


def _torch():
    torch = pytest.importorskip("torch")
    if not isinstance(getattr(torch, "__version__", None), str):
        pytest.skip("torch is stubbed (MagicMock) in this process")
    return torch


def _diag_fn(torch):
    ns: dict = {"torch": torch}
    exec(_extract_source(_TRAIN, "_group_grad_diag"), ns)
    return ns["_group_grad_diag"]


def _toy_optimizer(torch):
    torch.manual_seed(0)
    a = torch.nn.Parameter(torch.randn(4, 3))
    b = torch.nn.Parameter(torch.randn(5))
    c = torch.nn.Parameter(torch.randn(2, 2))
    opt = torch.optim.AdamW(
        [
            {"params": [a, b], "lr": 1e-3, "name": "lora"},
            {"params": [c], "lr": 5e-4, "name": "projection"},
        ]
    )
    return opt, (a, b, c)


def test_group_grad_diag_norms_match_manual_math():
    torch = _torch()
    opt, (a, b, c) = _toy_optimizer(torch)
    loss = (a**2).sum() + (b**2).sum() + (c**2).sum()
    loss.backward()
    torch.nn.utils.clip_grad_norm_([a, b, c], 1.0)  # diag sees POST-clip grads

    names, vals = _diag_fn(torch)(opt, torch.device("cpu"))
    gd = dict(zip(names, vals.tolist(), strict=True))

    lora_gsq = float((a.grad**2).sum() + (b.grad**2).sum())
    lora_psq = float((a.detach() ** 2).sum() + (b.detach() ** 2).sum())
    assert gd["grad_norm/lora"] == pytest.approx(math.sqrt(lora_gsq), rel=1e-5)
    assert gd["param_norm/lora"] == pytest.approx(math.sqrt(lora_psq), rel=1e-5)
    assert gd["nonfinite_grads/lora"] == 0.0

    # Host-side derivation (mirrors the log-boundary block in the train loop):
    # RMS = L2 / sqrt(numel); update_rms_est = lr * grad_rms.
    numel = a.numel() + b.numel()
    weight_rms = gd["param_norm/lora"] / math.sqrt(numel)
    manual_rms = math.sqrt(lora_psq / numel)  # sqrt(mean(p^2)) by definition
    assert weight_rms == pytest.approx(manual_rms, rel=1e-6)
    assert 1e-3 * gd["grad_norm/lora"] / math.sqrt(numel) == pytest.approx(
        1e-3 * math.sqrt(lora_gsq / numel), rel=1e-5
    )


def test_adam_update_norm_appears_after_first_step():
    torch = _torch()
    opt, (a, b, c) = _toy_optimizer(torch)
    diag = _diag_fn(torch)

    loss = (a**2).sum() + (b**2).sum() + (c**2).sum()
    loss.backward()
    _, vals0 = diag(opt, torch.device("cpu"))
    gd0 = dict(zip(_, vals0.tolist(), strict=True))
    assert gd0["adam_update_norm/lora"] == 0.0  # no optimizer state yet

    opt.step()
    opt.zero_grad(set_to_none=False)
    loss = (a**2).sum() + (b**2).sum() + (c**2).sum()
    loss.backward()
    names, vals = diag(opt, torch.device("cpu"))
    gd = dict(zip(names, vals.tolist(), strict=True))
    # exp_avg/(sqrt(exp_avg_sq)+eps) is ~1 per element right after step 1,
    # so the update norm is close to sqrt(numel) — just assert it's live.
    assert gd["adam_update_norm/lora"] > 0.0
    assert gd["adam_update_norm/projection"] > 0.0
