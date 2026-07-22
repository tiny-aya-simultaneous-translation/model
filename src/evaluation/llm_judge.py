"""GEMBA-style LLM adequacy judging via Gemini (temperature 0, rubric).

The judge rates ADEQUACY of the translation 1-5 given the gold source text
and the ASR transcript of the generated target audio (so ASR noise is part
of what it sees -- report next to the ASR judge's own error floor).
Two passes over the same inputs measure self-consistency; sub-0.9 agreement
means the ratings are too noisy to report. Needs GEMINI_API_KEY in the env.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_LANG_NAME = {"hi": "Hindi", "tr": "Turkish"}

_RUBRIC = """You are evaluating a {src_name}-to-{tgt_name} speech translation system.

SOURCE ({src_name}): {src}
TRANSLATION TRANSCRIPT ({tgt_name}, from ASR of the generated speech): {mt}

Rate the ADEQUACY of the translation on this scale:
5 = full meaning preserved
4 = most meaning preserved, minor omissions/errors
3 = about half the meaning preserved
2 = little meaning preserved
1 = none of the meaning preserved / unrelated

The transcript may contain ASR spelling artifacts; judge MEANING, not spelling.
Answer with ONLY the single digit rating (1-5)."""

_DIGIT_RE = re.compile(r"[1-5]")


def _parse_rating(text: str | None) -> int | None:
    if not text:
        return None
    m = _DIGIT_RE.search(text.strip()[:8])
    return int(m.group()) if m else None


def judge_adequacy(
    pairs: list[tuple[str, str]],
    src_lang: str,
    tgt_lang: str,
    model_name: str = "gemini-3.6-flash",
    passes: int = 2,
    max_workers: int = 8,
    max_retries: int = 3,
) -> dict:
    """Rate (source_text, generated_transcript) pairs; mean + self-consistency.

    Returns {"mean", "n", "ratings" (pass-1), "self_agreement"} -- agreement
    is the exact-match rate between passes (None when passes == 1).
    """
    from google import genai

    client = genai.Client()  # reads GEMINI_API_KEY from env

    def _one(src: str, mt: str) -> int | None:
        prompt = _RUBRIC.format(
            src_name=_LANG_NAME[src_lang], tgt_name=_LANG_NAME[tgt_lang],
            src=src, mt=mt,
        )
        for attempt in range(max_retries):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    # gemini-3.x flash is a THINKING model: thinking tokens
                    # count against max_output_tokens, so the old cap of 4 was
                    # consumed before any rating was emitted -> resp.text=None
                    # -> every score null. (thinking_config={"thinking_budget":0}
                    # is rejected 400 for this model.) The cap is a ceiling, not
                    # a target -- generation stops right after the single digit
                    # -- so a generous budget only costs tokens when thinking
                    # actually runs long. Verified live: 4 -> None, 1024 -> "1".
                    config={"temperature": 0.0, "max_output_tokens": 1024},
                )
                r = _parse_rating(resp.text)
                if r is not None:
                    return r
            except Exception as e:  # noqa: BLE001 - API flake: retry then None
                if attempt == max_retries - 1:
                    logger.error("gemini judge failed: %s", e)
            time.sleep(1.5 * (attempt + 1))
        return None

    def _pass() -> list[int | None]:
        results: dict[int, int | None] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_one, s, m): i for i, (s, m) in enumerate(pairs)}
            for fut in as_completed(futs):
                results[futs[fut]] = fut.result()
        return [results[i] for i in range(len(pairs))]

    all_passes = [_pass() for _ in range(max(1, passes))]
    first = all_passes[0]
    rated = [r for r in first if r is not None]
    out: dict = {
        "model": model_name,
        "n": len(rated),
        "n_failed": len(first) - len(rated),
        "mean": (sum(rated) / len(rated)) if rated else None,
        "ratings": first,
    }
    if len(all_passes) > 1:
        both = [
            (a, b) for a, b in zip(all_passes[0], all_passes[1], strict=True)
            if a is not None and b is not None
        ]
        out["self_agreement"] = (
            sum(1 for a, b in both if a == b) / len(both) if both else None
        )
    return out
