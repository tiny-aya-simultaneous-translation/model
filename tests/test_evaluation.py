"""Tests for the src/evaluation package (v0.3 evals program).

Pure-Python modules (normalize, subset, report skeleton) are tested directly;
tensor math (stats) is skipped on the torch-free CI runner via importorskip.
See docs/v0.3-evals-plan.md for the program design.

Run: ``python -m pytest tests/test_evaluation.py -v``
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest.mock import MagicMock

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.evaluation import normalize as N  # noqa: E402
from src.evaluation import report as R  # noqa: E402
from src.evaluation import subset as S  # noqa: E402

# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def test_normalize_hi_candrabindu_anusvara_unified():
    # हालाँकि (candrabindu) vs हालांकि (anusvara): orthographic variants that
    # the hindi-tts-probe report flagged as false WER hits.
    assert N.normalize_hi("हालाँकि") == N.normalize_hi("हालांकि")
    assert N.normalize_hi("दाएँ") == N.normalize_hi("दाएं")


def test_normalize_hi_devanagari_digits_to_ascii():
    assert N.normalize_hi("१५ अगस्त") == "15 अगस्त"
    # already-ASCII digits untouched
    assert N.normalize_hi("15 अगस्त") == "15 अगस्त"


def test_normalize_hi_danda_and_punct_stripped():
    assert N.normalize_hi("मुझे पता है।") == "मुझे पता है"
    assert N.normalize_hi('"वाह!"') == "वाह"


def test_normalize_hi_whitespace_collapse():
    assert N.normalize_hi("  एक   दिन \n ज़रूर ") == "एक दिन ज़रूर"


def test_normalize_tr_dotted_dotless_i():
    # İ -> i (not I -> i): plain lower() would merge distinct words.
    assert N.normalize_tr("İstanbul") == "istanbul"
    assert N.normalize_tr("ILIK") == "ılık"
    assert N.normalize_tr("Biliyorum, biliyorum.") == "biliyorum biliyorum"


def test_normalize_dispatch():
    assert N.normalize("वाह।", "hi") == "वाह"
    assert N.normalize("Evet!", "tr") == "evet"
    with pytest.raises(ValueError):
        N.normalize("x", "en")


def test_normalize_idempotent():
    for s, lang in [("हालाँकि १५।", "hi"), ("İki GÜN, ILIK!", "tr")]:
        once = N.normalize(s, lang)
        assert N.normalize(once, lang) == once


# ---------------------------------------------------------------------------
# subset
# ---------------------------------------------------------------------------


def _rows(n_per_dir=10):
    rows = []
    for d in ("tr->hi", "hi->tr"):
        for i in range(n_per_dir):
            rows.append({"pt_path": f"encoded/{d[:2]}_{i}.pt", "direction": d,
                         "sentence_id": i})
    return rows


def test_subset_deterministic_and_order_independent():
    rows = _rows(20)
    a = S.build_subset(rows, n_per_direction=5, seed=1337)
    b = S.build_subset(list(reversed(rows)), n_per_direction=5, seed=1337)
    assert a == b
    assert S.build_subset(rows, n_per_direction=5, seed=7) != a


def test_subset_per_direction_counts():
    picked = S.build_subset(_rows(20), n_per_direction=5, seed=1337)
    dirs = [r["direction"] for r in picked]
    assert dirs.count("tr->hi") == 5 and dirs.count("hi->tr") == 5


def test_subset_write_load_roundtrip(tmp_path):
    rows = S.build_subset(_rows(6), n_per_direction=3, seed=1337)
    p = tmp_path / "sub.jsonl"
    digest = S.write_subset(p, rows, {"name": "test-sub", "seed": 1337})
    loaded, header = S.load_subset(p)
    assert loaded == rows
    assert header["sha256"] == digest == S.rows_digest(rows)
    assert header["n"] == len(rows)


def test_subset_tamper_refused(tmp_path):
    rows = S.build_subset(_rows(6), n_per_direction=3, seed=1337)
    p = tmp_path / "sub.jsonl"
    S.write_subset(p, rows, {"name": "test-sub"})
    lines = p.read_text().splitlines()
    lines[2] = json.dumps({"pt_path": "encoded/EVIL.pt", "direction": "tr->hi"})
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="digest mismatch"):
        S.load_subset(p)
    # verify=False still loads (for forensic inspection)
    loaded, _ = S.load_subset(p, verify=False)
    assert loaded[1]["pt_path"] == "encoded/EVIL.pt"


def test_subset_missing_header_refused(tmp_path):
    p = tmp_path / "plain.jsonl"
    p.write_text(json.dumps({"pt_path": "a.pt"}) + "\n")
    with pytest.raises(ValueError, match="header"):
        S.load_subset(p)


# ---------------------------------------------------------------------------
# stats (tensor math -- skipped on torch-free CI)
# ---------------------------------------------------------------------------


def test_update_code_histogram_ignores_out_of_vocab():
    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
    torch = pytest.importorskip("torch")
    from src.evaluation.stats import (
        codebook_entropy_stats,
        new_code_histogram,
        update_code_histogram,
    )

    hist = new_code_histogram(2, vocab=2048)
    codes = torch.tensor([[0, 7, 7, 2048], [2047, -1, 5, 5]])  # 2048=SILENCE, -1 pad
    update_code_histogram(hist, codes)
    assert hist[0, 0] == 1 and hist[0, 7] == 2 and int(hist[0].sum()) == 3
    assert hist[1, 2047] == 1 and hist[1, 5] == 2 and int(hist[1].sum()) == 3

    ent, act = codebook_entropy_stats(hist)
    assert len(ent) == 2 and all(e > 0 for e in ent)
    assert abs(act[0] - 2 / 2048) < 1e-9


# ---------------------------------------------------------------------------
# text_metrics
# ---------------------------------------------------------------------------


def test_corpus_scores_normalized_chrfpp_primary():
    pytest.importorskip("sacrebleu")  # CI runner has no sacrebleu
    from src.evaluation.text_metrics import corpus_scores

    # candrabindu/anusvara + danda variance must NOT hurt the score
    sc = corpus_scores(
        hyps=["हालाँकि मुझे पता है।"] * 4,
        refs=["हालांकि मुझे पता है"] * 4,
        lang="hi",
        n_bootstrap=1,
    )
    assert sc["chrfpp"] == 100.0
    assert sc["n"] == 4
    if "wer" in sc:  # jiwer optional
        assert sc["wer"] == 0.0


def test_corpus_scores_ci_present_with_bootstrap():
    pytest.importorskip("sacrebleu")  # CI runner has no sacrebleu
    from src.evaluation.text_metrics import corpus_scores

    sc = corpus_scores(
        hyps=["kedi dün evin önünde oturdu", "bugün hava çok güzel ve açık"] * 4,
        refs=["kedi dün evin önünde uyudu", "bugün hava çok güzel ve kapalı"] * 4,
        lang="tr",
        n_bootstrap=50,
    )
    assert "chrfpp_ci95" in sc and "bleu_ci95" in sc
    assert 0 < sc["chrfpp"] < 100


def test_corpus_scores_refuses_mismatched():
    pytest.importorskip("sacrebleu")  # CI runner has no sacrebleu
    from src.evaluation.text_metrics import corpus_scores

    with pytest.raises(ValueError):
        corpus_scores(["a"], ["a", "b"], "tr")
    with pytest.raises(ValueError):
        corpus_scores([], [], "hi")


def test_paired_bootstrap_detects_worse_system():
    pytest.importorskip("sacrebleu")  # CI runner has no sacrebleu
    from src.evaluation.text_metrics import paired_bootstrap

    refs = ["kedi bugün evin önünde oturuyor ve uyuyor"] * 12
    good = ["kedi bugün evin önünde oturuyor ve bekliyor"] * 12
    bad = ["köpek dün masanın altında koştu"] * 12
    out = paired_bootstrap(good, bad, refs, "tr", n_samples=100)
    assert out["chrfpp"]["baseline"] > out["chrfpp"]["candidate"]
    assert out["chrfpp"]["p_value"] is not None


# ---------------------------------------------------------------------------
# frozen subset artifacts + proxy wiring
# ---------------------------------------------------------------------------

_SUBSET_FILE = REPO / "eval" / "subsets" / "v03-val-500.jsonl"


def test_frozen_val_subset_integrity():
    # The committed artifact must stay byte-stable: digest-verified load, both
    # directions at 250, gold text on every row (frozen 2026-07-15, host 0).
    rows, header = S.load_subset(_SUBSET_FILE)
    assert header["name"] == "v03-val-500" and header["seed"] == 1337
    assert len(rows) == 500
    dirs = [r["direction"] for r in rows]
    assert dirs.count("tr->hi") == 250 and dirs.count("hi->tr") == 250
    assert all(r.get("src_text") and r.get("tgt_text") for r in rows)


def test_frozen_fleurs_subset_integrity():
    # Real-human-speech FLEURS pairs = ACOUSTIC domain shift only: the audit
    # found 200/200 texts inside the training corpus (its FLORES slice --
    # FLEURS is FLoRes speech), so this set must never be described as
    # held-out TEXT. The recorded audit pins that fact.
    rows, header = S.load_subset(REPO / "eval" / "subsets" / "v03-fleurs-200.jsonl")
    assert header["name"] == "v03-fleurs-200"
    assert len(rows) == 200
    audit = header["overlap_audit"]
    assert audit["policy"] == "record"
    assert audit["n_overlapping"] == audit["n_drawn"] == 200
    assert ["source_type=fleurs_real"] == header["filters"]
    assert all(r.get("src_text") and r.get("tgt_text") for r in rows)


_PROXY_SRC = (REPO / "scripts" / "eval_translation_proxy.py").read_text()
_EC_SRC = (REPO / "scripts" / "eval_checkpoint.py").read_text()


def test_proxy_gold_metric_wiring():
    # legacy keys keep their frozen semantics
    assert '"eval/text_bleu_tf": bleu' in _PROXY_SRC
    assert '"eval/text_chrf_tf": chrf' in _PROXY_SRC
    # gold keys, per direction, chrF++ primary
    assert 'f"eval/gold_chrfpp_tf_{suffix}"' in _PROXY_SRC
    assert 'f"eval/gold_chrfpp_ar_{suffix}"' in _PROXY_SRC
    # frozen-subset selection refuses on missing rows
    assert "REFUSING" in _PROXY_SRC and "load_subset" in _PROXY_SRC
    # synthetic-reference disclosure travels with the numbers
    assert "machine-translated" in _PROXY_SRC


def test_ar_free_text_wiring():
    assert "free_text=False, return_text=False" in _EC_SRC
    assert 'ar_text[0, t] = bb_out["text_logits"][0, -1].argmax(dim=-1)' in _EC_SRC


# ---------------------------------------------------------------------------
# Tier 2/3 modules (all heavy imports are lazy -- importable torch-free)
# ---------------------------------------------------------------------------


def test_asr_judge_ids_are_org_benchmarked():
    from src.evaluation.asr_judge import JUDGE_IDS

    # hindi-tts-probe verdict: the Hindi fine-tune beats stock large-v3 by
    # ~9pp WER; changing a judge changes every ASR metric -- pin both ids.
    assert JUDGE_IDS["hi"] == "vasista22/whisper-hindi-large-v2"
    assert JUDGE_IDS["tr"] == "openai/whisper-large-v3"


def test_asr_judge_uses_forced_decoder_ids():
    # the vasista22 stale-generation_config workaround must not regress
    src = (REPO / "src" / "evaluation" / "asr_judge.py").read_text()
    assert "get_decoder_prompt_ids" in src
    assert "forced_decoder_ids=self._forced_ids" in src


def test_llm_judge_rating_parser():
    from src.evaluation.llm_judge import _parse_rating

    assert _parse_rating("4") == 4
    assert _parse_rating(" 3 \n") == 3
    assert _parse_rating("5 - full meaning") == 5
    assert _parse_rating("") is None
    assert _parse_rating(None) is None
    assert _parse_rating("no rating") is None


def test_latency_summary_math():
    from src.evaluation.latency import latency_summary

    out = latency_summary(
        full_fn=lambda: None, first_fn=lambda: None,
        frames=25, device="cpu", warmup=0, runs=2,
    )
    assert out["audio_s"] == 25 / 12.5
    assert out["rtf"] == out["gen_wall_s_mean"] / out["audio_s"]
    assert out["frames"] == 25 and out["runs"] == 2
    assert out["ttfa_s_mean"] >= 0


def test_semantic_lang_maps():
    from src.evaluation import semantic

    # SONAR ships speech encoders for exactly these (verified 2026-07-15)
    assert semantic._SPEECH_LANG3 == {"hi": "hin", "tr": "tur"}
    assert semantic._TEXT_LANG == {"hi": "hin_Deva", "tr": "tur_Latn"}
    assert "cometkiwi" in semantic.COMET_KIWI_ID.lower()


_RELEASE_SRC = (REPO / "scripts" / "eval_release.py").read_text()


def test_eval_release_wiring():
    # every stage present and dispatched
    for st in ("generate", "asr", "text", "mos", "semantic", "judge",
               "latency", "report"):
        assert f'"{st}" in stages' in _RELEASE_SRC
    # frozen-subset integrity gate + hub staging + greedy default
    assert "REFUSING" in _RELEASE_SRC
    assert 'startswith("hub:")' in _RELEASE_SRC
    assert '"--ar_temp", type=float, default=0.0' in _RELEASE_SRC
    # GT-audio topline + MOS delta + synthetic-refs disclosure travel along
    assert "asr_gt_topline" in _RELEASE_SRC
    assert "delta_gt" in _RELEASE_SRC
    assert "machine-translated" in _RELEASE_SRC


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def test_report_schema_and_roundtrip(tmp_path):
    res = R.build_results(
        checkpoint="gs://bucket/ckpts/step_001000",
        step=1000,
        subset_name="v03-val-500",
        subset_digest="a" * 64,
        subset_n=500,
        decoding={"mode": "greedy", "temp": 0.0},
        judges={"asr_hi": "vasista22/whisper-hindi-large-v2"},
        seed=1337,
    )
    assert res["schema_version"] == R.RESULTS_SCHEMA_VERSION
    assert res["checkpoint"]["step"] == 1000
    assert res["subset"]["sha256"] == "a" * 64
    assert res["environment"]["norm_version"] == N.NORM_VERSION
    assert res["metrics"] == {} and res["timings_s"] == {}

    p = tmp_path / "results.json"
    R.write_results(p, res)
    assert json.loads(p.read_text()) == res


def test_report_ckpt_step_local(tmp_path):
    ck = tmp_path / "step_000123"
    ck.mkdir()
    (ck / "metadata.json").write_text(json.dumps({"step": 123}))
    assert R.ckpt_step(str(ck)) == 123
