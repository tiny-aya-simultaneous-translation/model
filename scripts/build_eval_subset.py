"""Freeze an eval subset from a split manifest, enriched with gold text.

Runs wherever the split manifest AND the encoded corpus live (a TPU host, a
GPU box after staging, or locally against a downloaded corpus). Each drawn
row is enriched with the corpus .pt's gold fields (``src_text``/``tgt_text``,
langs, durations) so downstream scoring never needs the corpus for
references, and the frozen file is fully self-contained + self-verifying
(see src/evaluation/subset.py for the digest format).

Usage (host):
  uv run python scripts/build_eval_subset.py \
      --split_jsonl /mnt/data/splits/val.jsonl \
      --encoded_dir /mnt/data/encoded \
      --n_per_direction 250 --seed 1337 \
      --name v03-val-500 --out eval/subsets/v03-val-500.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.evaluation.report import resolve_git_sha  # noqa: E402
from src.evaluation.subset import build_subset, write_subset  # noqa: E402

# Gold fields copied from each .pt into the frozen row (verified live on the
# staged corpus, 2026-07-15 -- note: src_text/tgt_text, NOT source_text).
_PT_FIELDS = (
    "src_text", "tgt_text", "src_lang", "tgt_lang",
    "src_duration_s", "tgt_duration_s", "pair_id", "voice",
)


def _resolve_pt(p: str, encoded_dir: Path) -> Path:
    """Manifest path as-is, else encoded_dir/basename (dataset._resolve-lite)."""
    pp = Path(p)
    if pp.exists():
        return pp
    cand = encoded_dir / pp.name
    return cand if cand.exists() else pp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split_jsonl", required=True)
    ap.add_argument("--encoded_dir", required=True)
    ap.add_argument("--n_per_direction", type=int, default=250)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--filter", action="append", default=[],
                    help="key=value row filter, repeatable (e.g. "
                         "source_type=fleurs_real)")
    ap.add_argument("--exclude_norm_texts", default=None,
                    help="file of NORMALIZED texts (one/line); rows whose "
                         "normalized src/tgt text appears are excluded -- the "
                         "training-overlap (leakage) audit")
    ap.add_argument("--overlap_policy", choices=("exclude", "record"),
                    default="exclude",
                    help="'exclude' drops overlapping rows; 'record' keeps "
                         "them but writes the overlap stats into the header "
                         "(for sets that are text-leaked by construction, "
                         "e.g. FLEURS==FLoRes speech vs the corpus' FLORES "
                         "slice -- still valid as an ACOUSTIC domain-shift "
                         "set, never as held-out text)")
    args = ap.parse_args()

    import torch  # heavy: only needed for the .pt enrichment reads

    with open(args.split_jsonl) as f:
        rows = [json.loads(ln) for ln in f if ln.strip()]
    print(f"[subset] {len(rows)} manifest rows from {args.split_jsonl}", flush=True)

    for flt in args.filter:
        k, _, v = flt.partition("=")
        rows = [r for r in rows if str(r.get(k)) == v]
        print(f"[subset] filter {flt}: {len(rows)} rows remain", flush=True)

    # With an exclusion audit, over-draw so overlapped rows can be dropped
    # and still leave n_per_direction (deterministic either way).
    _excluding = args.exclude_norm_texts and args.overlap_policy == "exclude"
    overdraw = args.n_per_direction * (3 if _excluding else 1)
    picked = build_subset(rows, overdraw, seed=args.seed)
    encoded_dir = Path(args.encoded_dir)

    missing_pt, missing_text = 0, 0
    for r in picked:
        pt = _resolve_pt(r["pt_path"], encoded_dir)
        if not pt.exists():
            missing_pt += 1
            continue
        try:
            d = torch.load(pt, weights_only=False, mmap=True)
        except (TypeError, RuntimeError):
            d = torch.load(pt, weights_only=False)
        for k in _PT_FIELDS:
            v = d.get(k)
            if v is not None:
                r[k] = float(v) if k.endswith("_s") else v
        if not r.get("tgt_text"):
            missing_text += 1

    if missing_pt or missing_text:
        # A frozen subset with holes would silently shrink every future
        # corpus metric -- refuse instead.
        raise SystemExit(
            f"[subset] REFUSING to freeze: {missing_pt} unresolvable .pt, "
            f"{missing_text} rows without gold tgt_text"
        )

    overlap_audit = None
    if args.exclude_norm_texts:
        from src.evaluation.normalize import NORM_VERSION, normalize

        with open(args.exclude_norm_texts, encoding="utf-8") as f:
            excl = {ln.strip() for ln in f if ln.strip()}

        def _overlaps(r: dict) -> bool:
            return (
                normalize(r["src_text"], r["src_lang"]) in excl
                or normalize(r["tgt_text"], r["tgt_lang"]) in excl
            )

        n_overlap = sum(1 for r in picked if _overlaps(r))
        overlap_audit = {
            "exclude_file": os.path.basename(args.exclude_norm_texts),
            "n_exclusion_set": len(excl),
            "policy": args.overlap_policy,
            "n_overlapping": n_overlap,
            "n_drawn": len(picked),
            "norm_version": NORM_VERSION,
        }
        if args.overlap_policy == "exclude":
            kept = [r for r in picked if not _overlaps(r)]
            trimmed: list[dict] = []
            counts: dict[str, int] = {}
            for r in kept:
                d_ = r.get("direction", "")
                if counts.get(d_, 0) < args.n_per_direction:
                    trimmed.append(r)
                    counts[d_] = counts.get(d_, 0) + 1
            short = {d_: c for d_, c in counts.items() if c < args.n_per_direction}
            if short:
                raise SystemExit(
                    f"[subset] REFUSING: not enough non-overlapping rows {short} "
                    f"(excluded {n_overlap}); lower --n_per_direction or use "
                    "--overlap_policy record"
                )
            picked = trimmed
        print(f"[subset] overlap audit ({args.overlap_policy}): "
              f"{n_overlap}/{overlap_audit['n_drawn']} drawn rows overlap "
              "the training corpus texts", flush=True)

    meta = {
        "name": args.name,
        "seed": args.seed,
        "n_per_direction": args.n_per_direction,
        "source_split": os.path.basename(args.split_jsonl),
        "source_rows": len(rows),
        "filters": args.filter,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": resolve_git_sha(),
    }
    if overlap_audit:
        meta["overlap_audit"] = overlap_audit
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    digest = write_subset(args.out, picked, meta)
    dirs: dict[str, int] = {}
    for r in picked:
        dirs[r.get("direction", "?")] = dirs.get(r.get("direction", "?"), 0) + 1
    print(f"[subset] froze {len(picked)} rows {dirs} -> {args.out}")
    print(f"[subset] sha256={digest}")


if __name__ == "__main__":
    main()
