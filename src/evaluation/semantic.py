"""Semantic translation-quality metrics: BLASER-2.0 (speech) + COMET (text).

BLASER-2.0 rides SONAR embeddings and is modality-agnostic: QE mode scores
(source speech, generated speech) directly -- no ASR in the loop, so it is
immune to judge errors; Ref mode adds the gold target TEXT embedding (SONAR
speech encoders exist for both ``hin`` and ``tur``; text covers 200
languages). Scores calibrate to XSTS (1-5). License note: BLASER/SONAR
weights are CC-BY-NC-4.0 -- evaluation-only use here.

COMET runs on the ASR transcripts: CometKiwi (reference-free QE) and
COMET-ref (vs gold target text). ``Unbabel/wmt22-cometkiwi-da`` is a GATED
HF repo -- accept its license once with the eval token.

All imports are lazy: sonar-space/fairseq2 and unbabel-comet are heavy
[eval]-extra deps that must never leak into the training environment.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ISO-639-1 -> SONAR codes
_SPEECH_LANG3 = {"hi": "hin", "tr": "tur"}
_TEXT_LANG = {"hi": "hin_Deva", "tr": "tur_Latn"}

COMET_KIWI_ID = "Unbabel/wmt22-cometkiwi-da"
COMET_REF_ID = "Unbabel/wmt22-comet-da"


def _load_blaser(kind: str):
    """Load the BLASER-2.0 model, tolerating the card-name rename across
    sonar-space versions."""
    from sonar.models.blaser.loader import load_blaser_model

    names = {
        "qe": ("blaser_2_0_qe", "blaser_st2st_qe_v2_0"),
        "ref": ("blaser_2_0_ref", "blaser_st2st_ref_v2_0"),
    }[kind]
    last: Exception | None = None
    for name in names:
        try:
            return load_blaser_model(name).eval()
        except Exception as e:  # noqa: BLE001 - try the alternate card name
            last = e
    raise last  # type: ignore[misc]


def _prep_wavs(paths: list[str], sr_out: int = 16000) -> list[str]:
    """Normalize wavs for the SONAR speech encoders (16 kHz mono, |x| <= 1).

    Mimi-decoded wavs are 24 kHz and can exceed unit amplitude, which SONAR's
    audio validator rejects ("values must be between -1 and 1"). Peak-normalize
    (only when clipping) + resample to 16 kHz into temp files; return their
    paths (delete=False -- they outlive this call and are reaped at process
    exit, fine for a one-shot eval).
    """
    import tempfile

    import librosa
    import numpy as np
    import soundfile as sf

    out: list[str] = []
    for p in paths:
        wav, sr = sf.read(p, dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        peak = float(np.abs(wav).max()) if wav.size else 0.0
        if peak > 1.0:
            wav = wav / peak
        if sr != sr_out:
            wav = librosa.resample(wav, orig_sr=sr, target_sr=sr_out)
        tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        sf.write(tf.name, wav, sr_out)
        out.append(tf.name)
    return out


def blaser_scores(
    src_wavs: list[str],
    gen_wavs: list[str],
    src_lang: str,
    tgt_lang: str,
    ref_texts: list[str] | None = None,
    device: str = "cpu",
    batch_size: int = 4,
) -> dict:
    """BLASER-2.0 QE (+Ref when gold texts given) means over aligned lists."""
    import torch
    from sonar.inference_pipelines.speech import SpeechToEmbeddingModelPipeline
    from sonar.inference_pipelines.text import TextToEmbeddingModelPipeline

    dev = torch.device(device)
    src_wavs = _prep_wavs(src_wavs)
    gen_wavs = _prep_wavs(gen_wavs)
    src_enc = SpeechToEmbeddingModelPipeline(
        encoder=f"sonar_speech_encoder_{_SPEECH_LANG3[src_lang]}", device=dev
    )
    tgt_enc = SpeechToEmbeddingModelPipeline(
        encoder=f"sonar_speech_encoder_{_SPEECH_LANG3[tgt_lang]}", device=dev
    )
    src_emb = src_enc.predict(src_wavs, batch_size=batch_size)
    gen_emb = tgt_enc.predict(gen_wavs, batch_size=batch_size)

    out: dict = {"n": len(src_wavs)}
    with torch.no_grad():
        qe = _load_blaser("qe").to(dev)
        qe_scores = [
            float(qe(src=s.unsqueeze(0).to(dev), mt=m.unsqueeze(0).to(dev)).item())
            for s, m in zip(src_emb, gen_emb, strict=True)
        ]
        out["blaser_qe_mean"] = sum(qe_scores) / len(qe_scores)
        cos = torch.nn.functional.cosine_similarity(
            torch.stack(list(src_emb)), torch.stack(list(gen_emb))
        )
        out["cosine_src_mt_mean"] = float(cos.mean())

        if ref_texts:
            txt_enc = TextToEmbeddingModelPipeline(
                encoder="text_sonar_basic_encoder",
                tokenizer="text_sonar_basic_encoder",
                device=dev,
            )
            ref_emb = txt_enc.predict(ref_texts, source_lang=_TEXT_LANG[tgt_lang])
            ref_m = _load_blaser("ref").to(dev)
            ref_scores = [
                float(
                    ref_m(
                        src=s.unsqueeze(0).to(dev),
                        ref=r.unsqueeze(0).to(dev),
                        mt=m.unsqueeze(0).to(dev),
                    ).item()
                )
                for s, r, m in zip(src_emb, ref_emb, gen_emb, strict=True)
            ]
            out["blaser_ref_mean"] = sum(ref_scores) / len(ref_scores)
    return out


def comet_scores(
    srcs: list[str],
    hyps: list[str],
    refs: list[str] | None = None,
    model_id: str | None = None,
    device: str = "cpu",
    batch_size: int = 8,
) -> dict:
    """COMET system score: CometKiwi QE without refs, COMET-ref with them."""
    from comet import download_model, load_from_checkpoint

    mid = model_id or (COMET_REF_ID if refs else COMET_KIWI_ID)
    model = load_from_checkpoint(download_model(mid))
    if refs:
        data = [{"src": s, "mt": h, "ref": r} for s, h, r in zip(srcs, hyps, refs, strict=True)]
    else:
        data = [{"src": s, "mt": h} for s, h in zip(srcs, hyps, strict=True)]
    pred = model.predict(
        data, batch_size=batch_size, gpus=1 if device.startswith("cuda") else 0
    )
    return {
        "model": mid,
        "system_score": float(pred.system_score),
        "n": len(data),
    }
