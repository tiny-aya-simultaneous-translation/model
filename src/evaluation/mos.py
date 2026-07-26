"""Reference-free MOS predictors (DNSMOS + Distill-MOS) for generated audio.

MOS predictors are BIASED on codec-resynthesized speech (they were trained on
noise-suppression/TTS distributions, and non-English speech adds more skew),
so absolute numbers are close to meaningless here. The reportable quantity is
**delta_gt = mean(generated) - mean(ground-truth-target)** on the SAME
predictor: the GT target audio went through the identical TTS -> Mimi
encode/decode chain, isolating the model's own degradation. Report deltas;
keep absolutes in results.json for completeness only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MOS_SAMPLE_RATE = 16000  # both predictors expect 16 kHz


def dnsmos_scores(wav_paths: list[str]) -> list[float]:
    """DNSMOS ovrl_mos per file (speechmos package, bundled ONNX)."""
    import librosa
    from speechmos import dnsmos

    out = []
    for p in wav_paths:
        y, _sr = librosa.load(p, sr=_MOS_SAMPLE_RATE, mono=True)
        out.append(float(dnsmos.run(y, sr=_MOS_SAMPLE_RATE, verbose=False)["ovrl_mos"]))
    return out


def distill_mos_scores(wav_paths: list[str], device: str = "cpu") -> list[float]:
    """Distill-MOS per file (pip ``distillmos``; weights auto-download)."""
    import distillmos
    import torch
    import torchaudio

    model = distillmos.ConvTransformerSQAModel().to(device).eval()
    out = []
    with torch.no_grad():
        for p in wav_paths:
            x, sr = torchaudio.load(p)
            x = x.mean(dim=0, keepdim=True)  # mono
            if sr != _MOS_SAMPLE_RATE:
                x = torchaudio.functional.resample(x, sr, _MOS_SAMPLE_RATE)
            out.append(float(model(x.to(device)).item()))
    return out


def mos_summary(
    gen_paths: list[str],
    gt_paths: list[str],
    device: str = "cpu",
) -> dict:
    """Per-predictor means for generated + GT audio, and the delta that
    actually matters. Predictors that fail to import are skipped (recorded)."""
    summary: dict = {}
    for name, fn in (
        ("dnsmos", lambda ps: dnsmos_scores(ps)),
        ("distill_mos", lambda ps: distill_mos_scores(ps, device=device)),
    ):
        try:
            gen = fn(gen_paths)
            gt = fn(gt_paths)
        except ImportError as e:
            summary[name] = {"skipped": f"not installed ({e.name})"}
            continue
        except Exception as e:  # noqa: BLE001 - a broken predictor must not kill the sweep
            logger.error("%s scoring failed: %s", name, e)
            summary[name] = {"skipped": f"error: {e}"}
            continue
        mean_gen = sum(gen) / len(gen)
        mean_gt = sum(gt) / len(gt)
        summary[name] = {
            "generated_mean": mean_gen,
            "gt_mean": mean_gt,
            "delta_gt": mean_gen - mean_gt,
            "n": len(gen),
        }
    return summary
