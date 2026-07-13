"""Publish a run's checkpoint trajectory to HuggingFace as a Pythia-style suite.

WHY THIS EXISTS
---------------
The v0.3 long-horizon run keeps EVERY checkpoint (log-spaced early + every 1000
steps, keep_last_n: 0) for public release + mechanistic-interp deep dives. This
mirrors that trajectory into ONE HuggingFace model repo with one ``step-N``
branch per checkpoint (the Pythia/OLMo convention), weights-only (optimizer /
scheduler / rng blobs stay private in GCS). Consumers do
``from_pretrained(repo, revision="step-12000")``.

CPU-only; ``gs://`` checkpoints are staged with ``gcloud storage`` then pushed.
Idempotent per branch (re-running re-uploads; existing branches are reused).

Usage
-----
  HF_TOKEN=... python scripts/publish_checkpoint_suite.py \\
      --save-dir gs://tinyaya-stage2-eu/checkpoints/<run> \\
      --repo-id tiny-aya/tinyaya-stage2-v0.3 \\
      [--include-best] [--only-steps 1,2,4,1000,2000] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.training.checkpointing import (  # noqa: E402
    get_checkpoint_dirs,
    push_checkpoint_to_hub,
    read_checkpoint_metadata,
)

_COMPONENT_FILES = (
    "projection.pt",
    "depth_decoder.pt",
    "text_embed.pt",
    "audio_heads.pt",
    "model_audio_embed.pt",
)


def _stage(uri: str, dest: Path) -> Path:
    """Stage a checkpoint dir (local or gs://) to ``dest``, weights only."""
    dest.mkdir(parents=True, exist_ok=True)
    if not uri.startswith("gs:"):
        src = Path(uri)
        for f in ("metadata.json", *_COMPONENT_FILES):
            if (src / f).exists():
                shutil.copy2(src / f, dest / f)
        if (src / "peft_adapter").is_dir():
            shutil.copytree(src / "peft_adapter", dest / "peft_adapter", dirs_exist_ok=True)
        return dest
    uri = uri.rstrip("/")
    for f in ("metadata.json", *_COMPONENT_FILES):
        subprocess.run(
            ["gcloud", "storage", "cp", f"{uri}/{f}", str(dest)],
            check=False,
            capture_output=True,
        )
    peft_dst = dest / "peft_adapter"
    peft_dst.mkdir(exist_ok=True)
    subprocess.run(
        ["gcloud", "storage", "cp", "-r", f"{uri}/peft_adapter/*", str(peft_dst)],
        check=True,
        capture_output=True,
    )
    return dest


def _step_of(d: str) -> int:
    name = d.rstrip("/").rsplit("/", 1)[-1]
    try:
        return int(name.split("step_", 1)[1])
    except (IndexError, ValueError):
        return -1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save-dir", required=True, help="run save_dir (local or gs://)")
    ap.add_argument("--repo-id", required=True, help="target HF repo, e.g. org/name")
    ap.add_argument("--include-best", action="store_true", help="also push best_by_val -> branch 'best'")
    ap.add_argument("--only-steps", default="", help="comma list to restrict which steps to push")
    ap.add_argument("--dry-run", action="store_true", help="list what would be pushed, upload nothing")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token and not args.dry_run:
        raise SystemExit("HF_TOKEN env required (or use --dry-run)")

    dirs = get_checkpoint_dirs(args.save_dir)
    only = {int(s) for s in args.only_steps.split(",") if s.strip()} if args.only_steps else None
    plan = [(d, _step_of(d)) for d in dirs if _step_of(d) >= 0]
    if only is not None:
        plan = [(d, s) for d, s in plan if s in only]
    if args.include_best:
        plan.append((args.save_dir.rstrip("/") + "/best_by_val", "best"))

    print(f"[suite] {len(plan)} checkpoints -> https://huggingface.co/{args.repo_id}")
    for d, step in plan:
        branch = f"step-{step}" if isinstance(step, int) else str(step)
        print(f"[suite] {d} -> {args.repo_id}@{branch}")
        if args.dry_run:
            continue
        stage = Path(tempfile.mkdtemp(prefix="suite_"))
        try:
            _stage(d, stage)
            if not read_checkpoint_metadata(str(stage)):
                print(f"[suite]   SKIP {branch}: no metadata (incomplete)")
                continue
            push_checkpoint_to_hub(
                str(stage), args.repo_id, commit_message=f"checkpoint {branch}",
                token=token, revision=branch,
            )
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    print("[suite] done")


if __name__ == "__main__":
    main()
