"""Frozen eval subsets: seeded draws with a self-verifying digest.

Cross-checkpoint comparability requires the EXACT same samples every time,
forever. A subset file freezes that choice:

- line 1: ``{"_subset_header": {..., "sha256": <digest of rows>}}``
- lines 2..N: one manifest row per line (canonical JSON)

``load_subset`` recomputes the digest and refuses on mismatch, so a silently
edited/regenerated subset can never masquerade as the frozen one. The digest
also goes into every results.json (see report.py).

The draw itself is order-independent (rows are canonically sorted before the
seeded shuffle), so rebuilding from a differently-ordered manifest yields the
identical subset.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

HEADER_KEY = "_subset_header"


def _canonical(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rows_digest(rows: list[dict]) -> str:
    """Order-sensitive sha256 over the canonical row JSONs."""
    payload = "\n".join(_canonical(r) for r in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_subset(
    rows: list[dict],
    n_per_direction: int,
    seed: int = 1337,
    direction_key: str = "direction",
) -> list[dict]:
    """Deterministic per-direction draw of ``n_per_direction`` rows.

    Stable regardless of the input row order: candidates are canonically
    sorted before the seeded shuffle. Directions are emitted in sorted order.
    """
    by_dir: dict[str, list[dict]] = {}
    for r in rows:
        by_dir.setdefault(str(r.get(direction_key, "")), []).append(r)
    out: list[dict] = []
    for d in sorted(by_dir):
        cand = sorted(by_dir[d], key=_canonical)
        rng = random.Random(f"{seed}:{d}")
        rng.shuffle(cand)
        out.extend(cand[:n_per_direction])
    return out


def write_subset(path: str | Path, rows: list[dict], meta: dict) -> str:
    """Write header + rows; returns the frozen digest."""
    header = dict(meta)
    header["sha256"] = rows_digest(rows)
    header["n"] = len(rows)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({HEADER_KEY: header}, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(_canonical(r) + "\n")
    return header["sha256"]


def load_subset(path: str | Path, verify: bool = True) -> tuple[list[dict], dict]:
    """Load (rows, header); with ``verify`` (default) refuse on digest drift."""
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path}: empty subset file")
    head = json.loads(lines[0])
    if HEADER_KEY not in head:
        raise ValueError(f"{path}: first line is not a {HEADER_KEY} record")
    header = head[HEADER_KEY]
    rows = [json.loads(ln) for ln in lines[1:]]
    if verify:
        d = rows_digest(rows)
        if d != header.get("sha256"):
            raise ValueError(
                f"{path}: subset digest mismatch -- rows changed since freeze "
                f"({d[:12]}… != {str(header.get('sha256'))[:12]}…)"
            )
        if header.get("n") != len(rows):
            raise ValueError(f"{path}: header n={header.get('n')} but {len(rows)} rows")
    return rows, header
