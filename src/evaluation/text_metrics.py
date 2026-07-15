"""Corpus text metrics on normalized text, with bootstrap CIs.

chrF++ is the PRIMARY metric for this language pair (morphologically rich
Turkish / Devanagari Hindi; BLEU is noisy and near-meaningless below ~5 --
reported as secondary). Directions are NEVER pooled: callers score tr->hi
and hi->tr corpora separately, in the TARGET language's normalizer.

All inputs pass through src/evaluation/normalize first; results.json records
NORM_VERSION so scores are never compared across normalizer changes.
"""

from __future__ import annotations

from src.evaluation.normalize import normalize


def corpus_scores(
    hyps: list[str],
    refs: list[str],
    lang: str,
    n_bootstrap: int = 1000,
) -> dict:
    """chrF++/BLEU (+WER/CER when jiwer is installed) with 95% bootstrap CIs.

    Args:
        hyps/refs: raw (unnormalized) hypothesis/reference strings, aligned.
        lang: TARGET language of this corpus ('hi' | 'tr').
        n_bootstrap: bootstrap resamples for the CI (1 disables).
    """
    if not hyps or len(hyps) != len(refs):
        raise ValueError(f"bad corpus: {len(hyps)} hyps vs {len(refs)} refs")
    from sacrebleu.metrics import BLEU, CHRF

    h = [normalize(x, lang) for x in hyps]
    r = [normalize(x, lang) for x in refs]
    nb = max(1, int(n_bootstrap))
    chrf = CHRF(word_order=2).corpus_score(h, [r], n_bootstrap=nb)
    bleu = BLEU().corpus_score(h, [r], n_bootstrap=nb)
    out: dict = {
        "n": len(h),
        "chrfpp": float(chrf.score),
        "bleu": float(bleu.score),
    }
    if nb > 1:
        out["chrfpp_ci95"] = float(getattr(chrf, "_ci", 0.0))
        out["bleu_ci95"] = float(getattr(bleu, "_ci", 0.0))
    try:
        import jiwer

        pairs = [(rr, hh) for rr, hh in zip(r, h, strict=True) if rr]
        if pairs:
            rs, hs = (list(t) for t in zip(*pairs, strict=True))
            out["wer"] = float(jiwer.wer(rs, hs))
            out["cer"] = float(jiwer.cer(rs, hs))
    except ImportError:
        pass  # jiwer ships in the [eval] extra; WER/CER omitted without it
    return out


def paired_bootstrap(
    hyps_baseline: list[str],
    hyps_candidate: list[str],
    refs: list[str],
    lang: str,
    n_samples: int = 1000,
) -> dict:
    """Paired bootstrap A/B significance (checkpoint-vs-checkpoint, e.g.
    LAWA-average vs best_by_val). p_value is the candidate's, vs baseline."""
    from sacrebleu.metrics import BLEU, CHRF
    from sacrebleu.significance import PairedTest

    a = [normalize(x, lang) for x in hyps_baseline]
    b = [normalize(x, lang) for x in hyps_candidate]
    r = [normalize(x, lang) for x in refs]
    test = PairedTest(
        [("baseline", a), ("candidate", b)],
        {"chrfpp": CHRF(word_order=2), "bleu": BLEU()},
        references=[r],
        test_type="bs",
        n_samples=n_samples,
    )
    _sigs, scores = test()
    out: dict = {"n": len(r), "n_samples": n_samples}
    for mname, results in scores.items():
        if mname == "System":
            continue
        # sacrebleu re-labels metrics with its own display names (chrF2++);
        # emit stable keys.
        key = "chrfpp" if "chrf" in mname.lower() else mname.lower()
        base_res, cand_res = results
        out[key] = {
            "baseline": float(base_res.score),
            "candidate": float(cand_res.score),
            "p_value": None if cand_res.p_value is None else float(cand_res.p_value),
        }
    return out
