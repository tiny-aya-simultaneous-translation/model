"""Tests for StreamingTranslationDataset alignment resolution (text+audio fix).

WHY THIS EXISTS
---------------
v0.3 was misdiagnosed as "audio-only: the corpus ships no text alignments".
The real situation (verified live 2026-07-08): the tr-hi-mimi-encoded corpus
ships one `.src.alignments.json` + one `.tgt.alignments.json` per encoded
`.pt` (840,426 of each, 100% coverage) at the DATA ROOT -- while the shipped
split manifests point at `encoded/{stem}_src.json` (wrong name AND wrong
directory). The old `_resolve` never found them, so every text stream fell
back to all-ZERO_PADDING, and with `zero_padding_weight=0.0` the text loss
was structurally zero: silent forever.

These tests pin the fix:
* `_resolve_alignment` maps legacy manifest names to the real shipped layout;
* correctly-written manifest paths still resolve unchanged (both locations);
* `__getitem__` produces real (non-ZERO_PADDING) text tokens from that layout;
* the coverage guard raises when text is supervised but nothing resolves,
  and stays quiet for audio-only runs.

Run: `uv run pytest tests/test_dataset_alignments.py -v`
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

# These tests need REAL torch (tensor ops, torch.save). The CI "torch-free"
# unit-test job has no torch, and test_checkpoint_retention.py injects a
# MagicMock at sys.modules["torch"] -- which passes importorskip and hasattr
# checks (MagicMock fabricates any attribute), so verify __version__ is an
# actual str before importing modules that do `from torch.utils.data import`.
torch = pytest.importorskip("torch")
if not isinstance(getattr(torch, "__version__", None), str):
    pytest.skip(
        "real torch unavailable (torch-free CI job / stubbed module)",
        allow_module_level=True,
    )

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.data.dataset import StreamingTranslationDataset  # noqa: E402
from src.data.interleaver import ZERO_PADDING  # noqa: E402


class _FakeTokenizer:
    """Tokenizer stub: 1 deterministic id per word, no specials."""

    def encode(self, word, add_special_tokens=False):
        return [abs(hash(word)) % 1000 + 1]


def _write_corpus(root: pathlib.Path, stem: str, n_frames: int = 20) -> None:
    """Lay out one sample exactly as the shipped corpus does.

    `.pt` inside `encoded/`; the two alignment JSONs at the DATA ROOT with the
    real `{stem}.{src,tgt}.alignments.json` names.
    """
    enc = root / "encoded"
    enc.mkdir(parents=True, exist_ok=True)
    codes = torch.randint(0, 2048, (8, n_frames))
    torch.save({"src_codes": codes, "tgt_codes": codes.clone()}, enc / f"{stem}.pt")
    align = {
        "alignments": [
            ["Merhaba", [0.0, 0.4], "SPEAKER_MAIN"],
            ["dünya", [0.4, 0.9], "SPEAKER_MAIN"],
        ],
        "method": "uniform",
    }
    for kind in ("src", "tgt"):
        (root / f"{stem}.{kind}.alignments.json").write_text(json.dumps(align))


def _write_manifest(root: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    p = root / "train.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _row_legacy(stem: str) -> dict:
    """A manifest row as the PUBLISHED splits actually write it (wrong names)."""
    return {
        "pt_path": f"encoded/{stem}.pt",
        "src_align_path": f"encoded/{stem}_src.json",
        "tgt_align_path": f"encoded/{stem}_tgt.json",
        "direction": "tr->hi",
        "sentence_id": 0,
    }


def _row_correct(root: pathlib.Path, stem: str) -> dict:
    """A manifest row with the real shipped names at the data root."""
    return {
        "pt_path": f"encoded/{stem}.pt",
        "src_align_path": str(root / f"{stem}.src.alignments.json"),
        "tgt_align_path": str(root / f"{stem}.tgt.alignments.json"),
        "direction": "tr->hi",
        "sentence_id": 0,
    }


def _make_ds(manifest, root, **kw):
    return StreamingTranslationDataset(
        manifest,
        _FakeTokenizer(),
        max_frames=300,
        audio_frame_rate=12.5,
        encoded_dir=root / "encoded",
        **kw,
    )


def test_legacy_manifest_resolves_to_shipped_layout(tmp_path):
    stem = "conv_0_default_rev"
    _write_corpus(tmp_path, stem)
    ds = _make_ds(_write_manifest(tmp_path, [_row_legacy(stem)]), tmp_path)
    got = ds._resolve_alignment(f"encoded/{stem}_src.json", "src")
    assert got == tmp_path / f"{stem}.src.alignments.json"
    assert got.exists()
    got_t = ds._resolve_alignment(f"encoded/{stem}_tgt.json", "tgt")
    assert got_t == tmp_path / f"{stem}.tgt.alignments.json"


def test_correct_manifest_paths_untouched(tmp_path):
    stem = "conv_1_default"
    _write_corpus(tmp_path, stem)
    ds = _make_ds(_write_manifest(tmp_path, [_row_correct(tmp_path, stem)]), tmp_path)
    got = ds._resolve_alignment(str(tmp_path / f"{stem}.src.alignments.json"), "src")
    assert got == tmp_path / f"{stem}.src.alignments.json"


def test_getitem_produces_real_text_tokens(tmp_path):
    stem = "conv_2_female_brit"
    _write_corpus(tmp_path, stem)
    ds = _make_ds(_write_manifest(tmp_path, [_row_legacy(stem)]), tmp_path)
    item = ds[0]
    assert (item["text_ids"] != ZERO_PADDING).any(), (
        "text_ids is all ZERO_PADDING -- alignments did not resolve; the "
        "silent audio-only failure mode is back"
    )


def test_coverage_guard_raises_when_text_supervised(tmp_path):
    stem = "conv_3_default"
    _write_corpus(tmp_path, stem)
    # Remove the alignment files so nothing can resolve.
    for kind in ("src", "tgt"):
        (tmp_path / f"{stem}.{kind}.alignments.json").unlink()
    manifest = _write_manifest(tmp_path, [_row_legacy(stem)])
    with pytest.raises(FileNotFoundError, match="text_weight"):
        _make_ds(manifest, tmp_path, require_alignments=True)


def test_coverage_guard_silent_for_audio_only(tmp_path):
    stem = "conv_4_default"
    _write_corpus(tmp_path, stem)
    for kind in ("src", "tgt"):
        (tmp_path / f"{stem}.{kind}.alignments.json").unlink()
    manifest = _write_manifest(tmp_path, [_row_legacy(stem)])
    ds = _make_ds(manifest, tmp_path, require_alignments=False)
    assert len(ds) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
