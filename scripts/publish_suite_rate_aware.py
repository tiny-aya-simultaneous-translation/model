"""Rate-aware, resumable publisher for the FULL checkpoint suite.

WHY THIS EXISTS
---------------
``publish_checkpoint_suite.py`` pushes a checkpoint with one ``upload_file``
call PER FILE (~10 commits per checkpoint). The hub caps repository commits at
**128/hour**, so a full ~87-point suite (branches + ``main:checkpoints/``
mirror) exhausts the budget within minutes and the naive retry loop dies.

Two fixes, both here:

* **One commit per checkpoint** -- ``upload_folder`` uploads a staged bundle
  atomically, cutting commit count ~10x (87 x 2 modes = ~174 commits, i.e.
  ~2 hourly windows instead of ~12).
* **Budget-aware pacing** -- track commits spent in the current hour; when the
  cap is near, sleep until the window resets and continue. Rate-limit errors
  are caught and treated as "window exhausted", never as failure.

RESUMABLE + IDEMPOTENT: on every pass it asks the hub what already carries
weights and only publishes what is missing, so it can be killed and restarted
freely (and re-run after new checkpoints appear, e.g. an anneal leg).

Progress is published to a GCS status file so the run can be monitored without
SSH (see docs/tpu-runbook.md "Durable monitoring"). Intended to run in tmux ON
the TPU VM.

Usage:
    HF_TOKEN=... python scripts/publish_suite_rate_aware.py \\
        --save-dir gs://.../stage2-v6e16-mh-v03-r2 \\
        --repo-id tiny-aya-translate/tr-hi-s2st-v0.3 \\
        --status-uri gs://.../watch/fullsuite-status.txt [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ruff: noqa: E402,I001
# Reuse the weights-only staging helper (module-level import is side-effect
# free; its main() only runs under __main__). Both imports must follow the
# sys.path setup above.
import publish_checkpoint_suite as _suite
from src.training.checkpointing import get_checkpoint_dirs, read_checkpoint_metadata

WEIGHT_SUFFIXES = (".safetensors", ".pt", ".bin")
COMMIT_CAP_PER_HOUR = 128
# Leave headroom: other actors (the trainer's own pushes, a human) may also
# commit, and the cap is enforced server-side with no visibility.
SAFETY_MARGIN = 12
WINDOW_SECONDS = 3600


class CommitBudget:
    """Track commits spent in the rolling hour; sleep when the window is full."""

    def __init__(self, cap: int = COMMIT_CAP_PER_HOUR - SAFETY_MARGIN):
        self.cap = cap
        self.spent = 0
        self.window_start = time.time()

    def _reset_if_elapsed(self) -> None:
        if time.time() - self.window_start >= WINDOW_SECONDS:
            self.window_start = time.time()
            self.spent = 0

    def wait_for_slot(self, report) -> None:
        """Block until at least one commit can be spent."""
        self._reset_if_elapsed()
        if self.spent < self.cap:
            return
        sleep_s = int(WINDOW_SECONDS - (time.time() - self.window_start)) + 60
        report(f"budget exhausted ({self.spent}/{self.cap}); sleeping {sleep_s}s")
        time.sleep(max(sleep_s, 60))
        self.window_start = time.time()
        self.spent = 0

    def note_rate_limited(self, report) -> None:
        """Server said no: treat the window as spent regardless of our count."""
        self.spent = self.cap
        self.wait_for_slot(report)

    def spend(self, n: int = 1) -> None:
        self.spent += n


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "rate limit" in msg or "429" in msg or "too many requests" in msg


def published_with_weights(api, repo_id: str) -> tuple[set[str], set[str]]:
    """Return (branch labels, main-folder labels) that already carry weights."""
    from huggingface_hub import list_repo_refs

    branches = set()
    for ref in list_repo_refs(repo_id).branches:
        if ref.name in ("main",):
            continue
        try:
            files = api.list_repo_files(repo_id, revision=ref.name)
        except Exception:
            continue
        if any(f.endswith(WEIGHT_SUFFIXES) for f in files):
            branches.add(ref.name)
    folders: dict[str, bool] = {}
    for f in api.list_repo_files(repo_id):
        if not f.startswith("checkpoints/"):
            continue
        parts = f.split("/")
        if len(parts) < 3:
            continue
        folders.setdefault(parts[1], False)
        if f.endswith(WEIGHT_SUFFIXES):
            folders[parts[1]] = True
    return branches, {k for k, has in folders.items() if has}


def label_of(ckpt_dir: str) -> str:
    """`.../step_012000` -> `step-12000`; `.../best_by_val` -> `best`."""
    name = ckpt_dir.rstrip("/").rsplit("/", 1)[-1]
    if name.startswith("best"):
        return "best"
    if name.startswith("step_"):
        digits = name.split("step_", 1)[1].split("_")[0]
        try:
            return f"step-{int(digits)}"
        except ValueError:
            return name
    return name


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save-dir", required=True)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--status-uri", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token and not args.dry_run:
        raise SystemExit("HF_TOKEN env required (or use --dry-run)")

    from huggingface_hub import HfApi

    api = HfApi(token=token)

    def report(msg: str, phase: str = "RUNNING") -> None:
        line = f"[suite-ra] {msg}"
        print(line, flush=True)
        if not args.status_uri:
            return
        body = f"phase: {phase}\nupdated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\ndetail: {msg}\n"
        tmp = Path(tempfile.gettempdir()) / "suite_ra_status.txt"
        tmp.write_text(body)
        subprocess.run(
            ["gcloud", "storage", "cp", "-q", str(tmp), args.status_uri],
            check=False,
            capture_output=True,
        )

    # Deepest checkpoints first: the release candidates matter most, and a
    # long tail of early steps should never delay them.
    all_dirs = list(get_checkpoint_dirs(args.save_dir))
    best_dir = args.save_dir.rstrip("/") + "/best_by_val"
    work = [(d, label_of(d)) for d in all_dirs]
    work.sort(key=lambda t: -(int(t[1].split("-")[1]) if t[1].startswith("step-") else 10**9))
    work.insert(0, (best_dir, "best"))

    branches_ok, folders_ok = published_with_weights(api, args.repo_id)
    todo = [
        (d, lbl)
        for d, lbl in work
        if lbl not in branches_ok or lbl not in folders_ok
    ]
    report(
        f"{len(work)} checkpoints total; already complete: "
        f"{len(branches_ok & folders_ok)}; to publish: {len(todo)}",
        phase="START",
    )
    if args.dry_run:
        for d, lbl in todo[:20]:
            need = []
            if lbl not in branches_ok:
                need.append("branch")
            if lbl not in folders_ok:
                need.append("folder")
            print(f"  {lbl}: needs {'+'.join(need)}  <- {d}")
        print(f"  ... ({len(todo)} total)")
        return

    budget = CommitBudget()
    done = 0
    for d, lbl in todo:
        stage = Path(tempfile.mkdtemp(prefix="suitera_"))
        try:
            _suite._stage(d, stage)
            if not read_checkpoint_metadata(str(stage)):
                report(f"SKIP {lbl}: no metadata (incomplete checkpoint)")
                continue
            for mode in ("branch", "folder"):
                if mode == "branch" and lbl in branches_ok:
                    continue
                if mode == "folder" and lbl in folders_ok:
                    continue
                for attempt in range(1, 6):
                    budget.wait_for_slot(report)
                    try:
                        if mode == "branch":
                            api.create_branch(args.repo_id, branch=lbl, exist_ok=True)
                            api.upload_folder(
                                folder_path=str(stage),
                                repo_id=args.repo_id,
                                revision=lbl,
                                commit_message=f"checkpoint {lbl}",
                            )
                        else:
                            api.upload_folder(
                                folder_path=str(stage),
                                repo_id=args.repo_id,
                                path_in_repo=f"checkpoints/{lbl}",
                                revision="main",
                                commit_message=f"checkpoints/{lbl}",
                            )
                        budget.spend(1)
                        break
                    except Exception as e:  # noqa: BLE001
                        if _is_rate_limit(e):
                            report(f"{lbl}/{mode}: rate limited; waiting for window reset")
                            budget.note_rate_limited(report)
                            continue
                        report(f"{lbl}/{mode}: attempt {attempt} failed: {str(e)[:120]}")
                        time.sleep(30)
                else:
                    report(f"{lbl}/{mode}: GAVE UP after 5 attempts")
            done += 1
            report(f"published {lbl} ({done}/{len(todo)}; window {budget.spent}/{budget.cap})")
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    branches_ok, folders_ok = published_with_weights(api, args.repo_id)
    complete = len(branches_ok & folders_ok)
    report(
        f"complete: {complete} checkpoints have BOTH branch and folder weights",
        phase="DONE" if complete >= len(work) - 1 else "PARTIAL",
    )


if __name__ == "__main__":
    main()
