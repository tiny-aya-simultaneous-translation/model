"""Tests for scripts/average_checkpoints.py (LAWA uniform averaging).

WHY THIS EXISTS
---------------
The averaged checkpoint is a release candidate: a silent averaging bug
(dtype drift, key mismatch, wrong weighting) would ship a broken model that
still loads fine. These tests pin the math (exact uniform mean, fp32
accumulation cast back to source dtype), the layout (standard component
files + adapter + non-resumable metadata), and the checkpoint selectors.

Run: ``python -m pytest tests/test_average_checkpoints.py -v``
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _real_torch():
    from unittest.mock import MagicMock

    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
    return pytest.importorskip("torch")


def _mod():
    _real_torch()
    spec = importlib.util.spec_from_file_location(
        "avg_ckpt", REPO / "scripts" / "average_checkpoints.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_ckpt(root: pathlib.Path, name: str, step: int, proj_val: float, lora_val: float):
    torch = _real_torch()
    d = root / name
    (d / "peft_adapter").mkdir(parents=True)
    torch.save(
        {"weight": torch.full((2, 2), proj_val, dtype=torch.bfloat16)}, d / "projection.pt"
    )
    torch.save({"frozen": torch.ones(3)}, d / "depth_decoder.pt")  # identical across ckpts
    torch.save(
        {"lora_A.weight": torch.full((2,), lora_val)}, d / "peft_adapter" / "adapter_model.bin"
    )
    (d / "peft_adapter" / "adapter_config.json").write_text("{}")
    (d / "metadata.json").write_text(json.dumps({"step": step}))
    return d


def test_uniform_average_math_and_layout(tmp_path):
    torch = _real_torch()
    m = _mod()
    a = _make_ckpt(tmp_path, "step_000100", 100, proj_val=1.0, lora_val=0.0)
    b = _make_ckpt(tmp_path, "step_000200", 200, proj_val=3.0, lora_val=1.0)
    out = tmp_path / "avg"

    sys.argv = ["avg", str(a), str(b), "--out", str(out)]
    m.main()

    proj = torch.load(out / "projection.pt", weights_only=True)["weight"]
    assert proj.dtype == torch.bfloat16  # cast back to source dtype
    assert proj.float().mean().item() == pytest.approx(2.0)  # (1+3)/2
    lora = torch.load(out / "peft_adapter" / "adapter_model.bin", weights_only=True)
    assert lora["lora_A.weight"].mean().item() == pytest.approx(0.5)
    frozen = torch.load(out / "depth_decoder.pt", weights_only=True)["frozen"]
    assert torch.equal(frozen, torch.ones(3))  # frozen average is the identity
    assert (out / "peft_adapter" / "adapter_config.json").exists()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["save_kind"] == "lawa_average"
    assert meta["averaged_steps"] == [100, 200]
    assert not isinstance(meta.get("step"), int)  # NOT a resume target


def test_key_mismatch_rejected(tmp_path):
    torch = _real_torch()
    m = _mod()
    a = _make_ckpt(tmp_path, "step_000100", 100, 1.0, 0.0)
    b = _make_ckpt(tmp_path, "step_000200", 200, 3.0, 1.0)
    torch.save({"OTHER": torch.ones(1)}, b / "projection.pt")
    sys.argv = ["avg", str(a), str(b), "--out", str(tmp_path / "avg")]
    with pytest.raises(ValueError, match="key mismatch"):
        m.main()


def test_last_k_selector(tmp_path):
    m = _mod()
    for s in (100, 200, 300):
        _make_ckpt(tmp_path, f"step_{s:06d}", s, float(s), 0.0)

    class _A:
        checkpoints = []
        save_dir = str(tmp_path)
        last_k = 2
        around_best = 0

    sel = m._select_checkpoints(_A)
    assert [d.rsplit("step_", 1)[1] for d in sel] == ["000200", "000300"]


def test_around_best_selector(tmp_path):
    m = _mod()
    for s in (100, 200, 300, 400):
        _make_ckpt(tmp_path, f"step_{s:06d}", s, float(s), 0.0)
    best = tmp_path / "best_by_val"
    best.mkdir()
    (best / "metadata.json").write_text(json.dumps({"step": 200}))

    class _A:
        checkpoints = []
        save_dir = str(tmp_path)
        last_k = 3
        around_best = 3

    sel = m._select_checkpoints(_A)
    assert [d.rsplit("step_", 1)[1] for d in sel] == ["000100", "000200", "000300"]
