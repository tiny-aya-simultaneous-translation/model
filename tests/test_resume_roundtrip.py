"""Tests for the mid-training intervention (save -> stop -> resume) contract.

WHY THIS EXISTS
---------------
The v0.3 long-horizon plan (P0/Phase-1 audit, 2026-07-12) found four resume
bugs that a public keep-all-checkpoints run cannot tolerate:

1. GCS resume NEVER restored the optimizer: the trainer checked
   ``os.path.exists("gs://.../optimizer.pt")`` -- always False on a local
   filesystem check -- so every spot-preemption resume silently restarted
   Adam moments from zero. Fixed via ``fetch_checkpoint_file``.
2. ``gsutil -m cp`` uploads in arbitrary order, so a preemption mid-upload
   could land ``metadata.json`` (the resume gate) before ``optimizer.pt``.
   Fixed by staging metadata OUTSIDE the bulk dir and uploading it LAST.
3. ``find_latest_checkpoint`` could select a partially-uploaded dir (resume
   then started FRESH instead of falling back to the previous complete
   checkpoint). Fixed: only metadata-bearing ``step_<int>`` dirs qualify;
   the weights-only ``step_*_final`` canonical dir never qualifies.
4. The first optimizer step after every (re)start ran at full peak LR
   because ``WarmupCosineScheduler`` never sets LRs at construction and the
   loop steps the scheduler only AFTER the optimizer. Fixed by priming
   ``scheduler.step(start_step + 1)`` before the loop.

Pure-python behaviors are tested with the MagicMock-torch loader (pattern
from test_checkpoint_retention); the full save->load round-trip uses real
torch on a tiny fake composite model; trainer wiring is source-asserted
(pattern from test_group_diag) to avoid the heavy train-script imports.

Run: ``python -m pytest tests/test_resume_roundtrip.py -v``
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
_CKPT_PATH = REPO / "src" / "training" / "checkpointing.py"
_TRAIN_SRC = (REPO / "scripts" / "train_hierarchical.py").read_text()


def _load_ckpt_torchfree():
    """Import checkpointing.py with a stub torch (pure-python units only)."""
    if "torch" not in sys.modules:
        sys.modules["torch"] = MagicMock()
    spec = importlib.util.spec_from_file_location("ckpt_torchfree", _CKPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_step_dir(root: pathlib.Path, name: str, with_meta: bool) -> pathlib.Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "optimizer.pt").write_bytes(b"x")
    if with_meta:
        (d / "metadata.json").write_text("{}")
    return d


# ---- completeness-gated resume selection (bugs 2+3) -------------------------


def test_find_latest_skips_incomplete_and_final_dirs(tmp_path):
    ckpt = _load_ckpt_torchfree()
    _make_step_dir(tmp_path, "step_000500", with_meta=True)
    _make_step_dir(tmp_path, "step_001000", with_meta=False)  # interrupted upload
    _make_step_dir(tmp_path, "step_001000_final", with_meta=True)  # weights-only
    latest = ckpt.find_latest_checkpoint(str(tmp_path))
    assert latest is not None
    assert latest.rstrip("/").endswith("step_000500")


def test_get_checkpoint_dirs_requires_metadata(tmp_path):
    ckpt = _load_ckpt_torchfree()
    _make_step_dir(tmp_path, "step_000100", with_meta=True)
    _make_step_dir(tmp_path, "step_000200", with_meta=False)
    names = [d.rsplit("/", 1)[-1] for d in ckpt.get_checkpoint_dirs(str(tmp_path))]
    assert names == ["step_000100"]


def test_get_checkpoint_dirs_gcs_batched_metadata_gate(monkeypatch, tmp_path):
    """GCS branch: one batched ls decides completeness; incomplete dirs drop."""
    ckpt = _load_ckpt_torchfree()
    base = "gs://bkt/run"

    def fake_run(args, capture_output=True, text=True):
        r = types.SimpleNamespace(returncode=0, stderr="")
        if args[:2] == ["gsutil", "ls"] and len(args) == 3:
            # top-level listing: three step dirs + best_by_val + canonical final
            r.stdout = (
                f"{base}/step_000500/\n{base}/step_001000/\n"
                f"{base}/step_001000_final/\n{base}/best_by_val/\n"
            )
        else:
            # metadata gate: only step_000500 finished its upload
            r.stdout = f"{base}/step_000500/metadata.json\n"
        return r

    monkeypatch.setattr(
        ckpt, "subprocess", types.SimpleNamespace(run=fake_run), raising=False
    )
    monkeypatch.setitem(sys.modules, "subprocess", types.SimpleNamespace(run=fake_run))
    dirs = ckpt.get_checkpoint_dirs(base)
    assert dirs == [f"{base}/step_000500"]


# ---- fetch_checkpoint_file (bug 1) ------------------------------------------


def test_fetch_checkpoint_file_local(tmp_path):
    ckpt = _load_ckpt_torchfree()
    d = _make_step_dir(tmp_path, "step_000500", with_meta=True)
    assert ckpt.fetch_checkpoint_file(str(d), "optimizer.pt") == str(d / "optimizer.pt")
    assert ckpt.fetch_checkpoint_file(str(d), "rng.pt") is None


def test_fetch_checkpoint_file_gcs(monkeypatch):
    ckpt = _load_ckpt_torchfree()
    calls: list[list[str]] = []

    def fake_run(args, capture_output=True, text=True):
        calls.append(list(args))
        ok = args[-2].endswith("/optimizer.pt")
        if ok:
            pathlib.Path(args[-1]).write_bytes(b"osd")
        return types.SimpleNamespace(returncode=0 if ok else 1, stdout="", stderr="")

    monkeypatch.setitem(sys.modules, "subprocess", types.SimpleNamespace(run=fake_run))
    got = ckpt.fetch_checkpoint_file("gs://bkt/run/step_000500", "optimizer.pt")
    assert got is not None and pathlib.Path(got).read_bytes() == b"osd"
    assert ckpt.fetch_checkpoint_file("gs://bkt/run/step_000500", "rng.pt") is None
    assert all(a[0] == "gsutil" for a in calls)


# ---- full save -> resume round-trip (real torch) ----------------------------


def _real_torch():
    """Return the REAL torch, purging any MagicMock a sibling test installed.

    Without this, ``pytest.importorskip("torch")`` happily returns the stub and
    every ``torch.equal`` assert becomes a truthy MagicMock -- a silent pass.
    """
    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
    return pytest.importorskip("torch")


def _fake_composite():
    torch = _real_torch()
    nn = torch.nn

    class _FakePeft(nn.Module):
        # **kwargs: tolerate HF/peft-convention kwargs the trainer states
        # explicitly (e.g. save_embedding_layers=True).
        def save_pretrained(self, d, state_dict=None, safe_serialization=False, **kwargs):
            pathlib.Path(d).mkdir(parents=True, exist_ok=True)
            torch.save(state_dict or {}, pathlib.Path(d) / "adapter_model.bin")

    class _FakeBackbone(nn.Module):
        def __init__(self):
            super().__init__()
            self.model = _FakePeft()
            self.text_embed = nn.Linear(4, 4, bias=False)
            self.audio_heads = nn.Linear(4, 4, bias=False)

    class _FakeComposite(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = _FakeBackbone()
            self.projection = nn.Linear(4, 4, bias=False)
            self.depth_decoder = nn.Linear(4, 4, bias=False)

    torch.manual_seed(0)
    return _FakeComposite()


def _load_ckpt_real_torch():
    """Import checkpointing.py against the REAL torch for round-trip tests."""
    _real_torch()
    spec = importlib.util.spec_from_file_location("ckpt_real", _CKPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_adamw_step(model):
    import torch

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    model.projection(torch.randn(2, 4)).sum().backward()
    for p in model.parameters():
        if p.grad is None:
            p.grad = torch.zeros_like(p)
    opt.step()
    return opt


def test_save_then_resume_restores_optimizer_and_loop_state(tmp_path):
    torch = _real_torch()
    ckpt = _load_ckpt_real_torch()
    model = _fake_composite()
    opt = _one_adamw_step(model)

    d = tmp_path / "step_000010"
    ckpt.save_checkpoint(
        model,
        opt,
        None,
        10,
        str(d),
        extra_state={"best_val": 3.5, "patience_left": 4},
    )
    for fname in ("optimizer.pt", "rng.pt", "metadata.json", "projection.pt"):
        assert (d / fname).exists(), fname
    meta = json.loads((d / "metadata.json").read_text())
    assert meta["step"] == 10 and meta["best_val"] == 3.5 and meta["patience_left"] == 4

    # fresh model + optimizer; drop the fake adapter so the peft path is skipped
    import shutil

    shutil.rmtree(d / "peft_adapter")
    model2 = _fake_composite()
    opt2 = torch.optim.AdamW(model2.parameters(), lr=1e-3)
    step = ckpt.load_checkpoint(model2, opt2, None, str(d))
    assert step == 10
    # weights round-trip
    assert torch.equal(model2.projection.weight, model.projection.weight)
    # Adam moments round-trip (the GCS-resume bug lost exactly this state)
    s1 = opt.state_dict()["state"]
    s2 = opt2.state_dict()["state"]
    assert set(s1.keys()) == set(s2.keys()) and len(s1) > 0
    for k in s1:
        assert torch.equal(s1[k]["exp_avg"], s2[k]["exp_avg"])
        assert torch.equal(s1[k]["exp_avg_sq"], s2[k]["exp_avg_sq"])


def test_gcs_upload_sends_metadata_last(tmp_path, monkeypatch):
    """The bulk upload must not contain metadata.json; it goes up alone, after."""
    _real_torch()
    ckpt = _load_ckpt_real_torch()
    model = _fake_composite()
    opt = _one_adamw_step(model)

    events: list[tuple[str, bool]] = []

    def fake_bulk(src_dir, gcs_dest, attempts=4):
        events.append(("bulk", pathlib.Path(src_dir, "metadata.json").exists()))

    def fake_single(src_file, gcs_dest_dir, attempts=4):
        events.append(("meta", src_file.endswith("metadata.json")))

    monkeypatch.setattr(ckpt, "_gsutil_cp_into", fake_bulk)
    monkeypatch.setattr(ckpt, "_gsutil_cp_file", fake_single)
    ckpt.save_checkpoint(model, opt, None, 10, "gs://bkt/run/step_000010")
    assert events == [("bulk", False), ("meta", True)]


# ---- scheduler priming (bug 4) ----------------------------------------------


def test_scheduler_construction_leaves_peak_lr_and_priming_fixes_it():
    torch = _real_torch()
    sys.path.insert(0, str(REPO))
    from src.training.scheduler import WarmupCosineScheduler

    lin = torch.nn.Linear(2, 2)
    opt = torch.optim.AdamW(lin.parameters(), lr=1.0)
    sched = WarmupCosineScheduler(opt, warmup_steps=100, total_steps=1000)
    # documents WHY priming is needed: construction leaves peak lr
    assert opt.param_groups[0]["lr"] == 1.0
    sched.step(0 + 1)  # fresh start: first step must be warmup lr, not peak
    assert opt.param_groups[0]["lr"] == pytest.approx(1 / 100)
    sched.step(500 + 1)  # resume at step 500: first step must be cosine lr
    assert 0.0 < opt.param_groups[0]["lr"] < 1.0
    assert opt.param_groups[0]["lr"] != pytest.approx(1.0)


# ---- trainer wiring (source asserts, no heavy imports) ----------------------


def test_trainer_primes_scheduler_before_loop():
    assert "scheduler.step(start_step + 1)" in _TRAIN_SRC


def test_trainer_restores_optimizer_via_fetch_and_hard_fails():
    assert 'fetch_checkpoint_file(resume_dir, "optimizer.pt")' in _TRAIN_SRC
    assert "allow_fresh_optimizer" in _TRAIN_SRC
    # the old always-False GCS existence check must be gone
    assert 'os.path.join(resume_dir, "optimizer.pt")' not in _TRAIN_SRC


def test_trainer_persists_and_restores_early_stop_state():
    assert '"best_val": best_val' in _TRAIN_SRC
    assert '"patience_left": _patience_left' in _TRAIN_SRC
    assert 'resume_meta.get("best_val"' in _TRAIN_SRC
    assert 'resume_meta.get("patience_left"' in _TRAIN_SRC


def test_defaults_gained_resume_and_debug_knobs():
    import ast

    tree = ast.parse(_TRAIN_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets
        ):
            defaults = ast.literal_eval(node.value)
            assert defaults["train"]["allow_fresh_optimizer"] is False
            assert defaults["train"]["debug_input_sharding"] is False
            return
    raise AssertionError("DEFAULTS not found")
