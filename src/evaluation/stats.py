"""Codebook-distribution health stats (collapse instrument).

``codebook_entropy_stats`` moved here verbatim from
``scripts/train_hierarchical.py`` (the trainer imports it back under its old
name) so the offline evaluator can score GENERATION-time code usage with the
same math as the in-loop validation histogram.

This module never imports torch at module level (torch-free CI imports it);
the functions operate on tensors via method calls only.
"""

from __future__ import annotations


def codebook_entropy_stats(hist) -> tuple[list[float], list[float]]:
    """Per-codebook prediction-distribution health from a count histogram.

    Args:
        hist: [num_codebooks, vocab] CPU tensor of predicted-code counts
            (sentinel column already dropped by the caller).

    Returns:
        (entropy_bits, active_frac) lists, one entry per codebook.
        Entropy of the empirical prediction distribution in BITS
        (max = log2(vocab), e.g. 11.0 for the 2048-code Mimi books);
        active_frac = fraction of the vocab predicted at least once.
        A collapsing codebook shows falling entropy + active_frac -- this
        directly instruments the deep-codebook-collapse failure mode.
    """
    entropy_bits: list[float] = []
    active_frac: list[float] = []
    for c in range(hist.shape[0]):
        h = hist[c].double()
        total = float(h.sum())
        if total <= 0:
            entropy_bits.append(0.0)
            active_frac.append(0.0)
            continue
        p = h / total
        nz = p[p > 0]
        entropy_bits.append(float(-(nz * nz.log2()).sum()))
        active_frac.append(float((h > 0).double().mean()))
    return entropy_bits, active_frac


def new_code_histogram(num_codebooks: int, vocab: int = 2048):
    """Fresh [num_codebooks, vocab] long count histogram."""
    import torch

    return torch.zeros(num_codebooks, vocab, dtype=torch.long)


def update_code_histogram(hist, codes):
    """Accumulate generated codes into ``hist`` in place.

    Args:
        hist: [num_codebooks, vocab] long tensor.
        codes: [num_codebooks, T] long tensor of generated codes; ids outside
            [0, vocab) -- e.g. SILENCE_TOKEN 2048 -- are ignored, mirroring
            the sentinel-drop in the trainer's val histogram.
    """
    vocab = hist.shape[1]
    for c in range(hist.shape[0]):
        v = codes[c]
        v = v[(v >= 0) & (v < vocab)]
        if v.numel():
            hist[c] += v.bincount(minlength=vocab)
    return hist
