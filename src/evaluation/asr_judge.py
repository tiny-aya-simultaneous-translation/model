"""Pluggable ASR judges for ASR-chrF/BLEU/WER scoring of generated audio.

Judge choices are org-benchmarked (hindi-tts-probe, N=100 synthetic Hindi):
``vasista22/whisper-hindi-large-v2`` corpus WER 20.11% vs whisper-large-v3's
29.43% -- the Hindi-specialized fine-tune is the Hindi judge; Turkish uses
stock whisper-large-v3. The vasista22 checkpoint ships an outdated
generation_config (empty ``suppress_tokens``; breaks the ``language=`` kwarg
on newer transformers), so BOTH judges are loaded via
WhisperForConditionalGeneration + explicit ``forced_decoder_ids`` -- the
workaround documented in the probe report.

A Gemini referee (port of sound-quality-check's transcriber, with the
Turkish-hardcoded prompt replaced by a ``language`` parameter) cross-checks a
sample of the whisper transcripts; disagreement bounds judge-induced error.

results.json must always record the judge id (see JUDGE_IDS) next to any
ASR-based metric -- scores are not comparable across judges.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

JUDGE_IDS = {
    "hi": "vasista22/whisper-hindi-large-v2",
    "tr": "openai/whisper-large-v3",
}

_LANG_NAME = {"hi": "Hindi", "tr": "Turkish"}

_ASR_SAMPLE_RATE = 16000


class WhisperJudge:
    """Batch Whisper transcription for one language (lazy model load)."""

    def __init__(self, lang: str, device: str = "cuda", batch_size: int = 8,
                 model_id: str | None = None):
        if lang not in JUDGE_IDS:
            raise ValueError(f"no ASR judge for language {lang!r}")
        self.lang = lang
        self.model_id = model_id or JUDGE_IDS[lang]
        self.device = device
        self.batch_size = batch_size
        self._model = None
        self._processor = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        logger.info("loading ASR judge %s on %s", self.model_id, self.device)
        self._processor = WhisperProcessor.from_pretrained(self.model_id)
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        self._model = WhisperForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=dtype
        ).to(self.device).eval()
        # vasista22/whisper-hindi-large-v2 ships an EMPTY suppress_tokens.
        # transformers' _prepare_decoder_input_ids reads suppress_tokens[-2]
        # (the prev_start_of_text sentinel) and IndexErrors on a size-0 tensor.
        # None == "suppress nothing" (matches the empty intent) and takes the
        # safe `is None` branch. Only touch a degenerate/too-short config so
        # large-v3's real suppression list is left untouched.
        _gc = self._model.generation_config
        _st = getattr(_gc, "suppress_tokens", None)
        if _st is not None and len(_st) < 2:
            _gc.suppress_tokens = None
        # forced_decoder_ids path: survives the vasista22 stale
        # generation_config that breaks generate(language=...).
        self._forced_ids = self._processor.tokenizer.get_decoder_prompt_ids(
            language=self.lang, task="transcribe"
        )

    def transcribe(self, wav_paths: list[str]) -> list[str]:
        """Transcripts aligned with ``wav_paths`` (16 kHz mono resample)."""
        self._load()
        import librosa
        import torch

        out: list[str] = []
        for i in range(0, len(wav_paths), self.batch_size):
            batch = wav_paths[i : i + self.batch_size]
            waves = [
                librosa.load(p, sr=_ASR_SAMPLE_RATE, mono=True)[0] for p in batch
            ]
            feats = self._processor(
                waves, sampling_rate=_ASR_SAMPLE_RATE, return_tensors="pt"
            ).input_features.to(self.device).to(self._model.dtype)
            with torch.no_grad():
                ids = self._model.generate(
                    feats, forced_decoder_ids=self._forced_ids, max_new_tokens=256
                )
            out.extend(self._processor.batch_decode(ids, skip_special_tokens=True))
        return [t.strip() for t in out]


def transcribe_gemini(
    wav_paths: list[str],
    language: str,
    model_name: str = "gemini-3.6-flash",
    max_workers: int = 8,
    max_retries: int = 3,
) -> list[str | None]:
    """Gemini referee transcription (org port + language parameter).

    Returns transcripts aligned with ``wav_paths`` (None on failure). Needs
    GEMINI_API_KEY in the environment (never printed).
    """
    from google import genai
    from google.genai import types

    client = genai.Client()  # reads GEMINI_API_KEY from env
    prompt = (
        f"Transcribe the following {_LANG_NAME[language]} audio exactly as "
        "spoken. Output only the transcription text, no punctuation. If you "
        "cannot understand the audio, output an empty string."
    )

    def _one(path: str) -> str | None:
        with open(path, "rb") as f:
            audio_bytes = f.read()
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=[
                        prompt,
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                    ],
                )
                return (resp.text or "").strip()
            except Exception as e:  # noqa: BLE001 - API flake: retry then None
                if attempt < max_retries - 1:
                    time.sleep(2.0 * (attempt + 1))
                else:
                    logger.error("gemini failed for %s: %s", path, e)
        return None

    results: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, p): p for p in wav_paths}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
    return [results[p] for p in wav_paths]
