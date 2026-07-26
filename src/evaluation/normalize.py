"""Text normalization for TR/HI eval scoring (WER/CER/BLEU/chrF).

Every text metric in the evals program normalizes BOTH reference and
hypothesis through these functions first; results.json records
``NORM_VERSION`` so scores are never compared across normalizer changes.

Ports the hindi-tts-probe scorer's ``norm()`` (NFC + lowercase + punct strip
+ whitespace collapse) and fixes the two scoring bugs its report flagged:

- candrabindu vs anusvara (``हालाँकि`` vs ``हालांकि``) counted as word errors;
- ASCII vs Devanagari digit forms (whisper-large-v3 emits ``5`` where refs
  write ``५`` or ``पाँच``) -- digits are harmonized to ASCII (the lexical
  five-vs-5 case is left alone: that is a genuine ASR/TTS error).

Turkish additionally needs locale-aware casefolding: ``İ``→``i`` and
``I``→``ı`` BEFORE generic ``lower()``, which would otherwise map ``I``→``i``
and merge distinct words.
"""

from __future__ import annotations

import re
import unicodedata

NORM_VERSION = "hi-tr-v1"

# Latin + Devanagari punctuation (danda, double danda, abbreviation sign) +
# common quote/dash forms. Replaced with a space, then whitespace-collapsed.
_PUNCT = "।॥॰,.!?:;\"'`()[]{}<>—–‐‑‒-…‘’“”„/\\|~*@#%^&_+="
_PUNCT_RE = re.compile("[" + re.escape(_PUNCT) + "]")
_WS_RE = re.compile(r"\s+")

# Devanagari digits U+0966..U+096F -> ASCII.
_DEVANAGARI_DIGITS = {0x0966 + i: str(i) for i in range(10)}


def _strip_punct_ws(s: str) -> str:
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip()


def normalize_hi(s: str) -> str:
    """Normalize Hindi (Devanagari) text for metric computation."""
    s = unicodedata.normalize("NFC", s)
    # candrabindu -> anusvara: pure orthographic variance, not an error
    s = s.replace("ँ", "ं")
    s = s.translate(_DEVANAGARI_DIGITS)
    s = s.lower()  # no-op for Devanagari; normalizes embedded Latin
    return _strip_punct_ws(s)


def normalize_tr(s: str) -> str:
    """Normalize Turkish text for metric computation (dotted/dotless i)."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("İ", "i").replace("I", "ı").lower()
    return _strip_punct_ws(s)


def normalize(s: str, lang: str) -> str:
    """Dispatch on language code ('hi' | 'tr')."""
    if lang == "hi":
        return normalize_hi(s)
    if lang == "tr":
        return normalize_tr(s)
    raise ValueError(f"unsupported eval language: {lang!r} (expected 'hi' or 'tr')")
