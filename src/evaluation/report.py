"""Versioned eval results + W&B backfill + optional hub push.

Every evaluator (eval_release.py, eval_translation_proxy.py) reports through
this schema so a number can always be traced to: WHICH checkpoint, WHICH
frozen subset (by digest), WHICH judges/normalizer/metric libs, and WHICH
decoding config produced it. Backfill mirrors the proxy's contract: metrics
carry ``global_step`` so points land on the training run's x-axis.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from src.evaluation.normalize import NORM_VERSION

RESULTS_SCHEMA_VERSION = 1


def resolve_git_sha() -> str:
    """BUILD_SHA (deployed tarballs) -> git rev-parse -> 'unknown'."""
    sha = os.environ.get("BUILD_SHA", "").strip()
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def ckpt_step(checkpoint: str) -> int:
    """The checkpoint's own global step, from its metadata.json (local/gs://)."""
    uri = os.path.join(checkpoint, "metadata.json")
    if checkpoint.startswith("gs://"):
        raw = subprocess.run(
            ["gsutil", "cat", uri], capture_output=True, text=True
        ).stdout
    else:
        with open(uri) as f:
            raw = f.read()
    return int(json.loads(raw)["step"])


def metric_lib_versions() -> dict[str, str]:
    """Versions of whichever metric libraries are importable (best-effort)."""
    versions: dict[str, str] = {}
    for name in ("sacrebleu", "jiwer", "speechmos", "distillmos", "comet", "sonar"):
        try:
            mod = __import__(name)
            versions[name] = str(getattr(mod, "__version__", "installed"))
        except Exception:  # noqa: BLE001 - absent/broken lib is not an error here
            continue
    return versions


def build_results(
    *,
    checkpoint: str,
    step: int,
    subset_name: str,
    subset_digest: str,
    subset_n: int,
    decoding: dict,
    revision: str | None = None,
    judges: dict | None = None,
    seed: int | None = None,
) -> dict:
    """Results skeleton; evaluators fill ``metrics``/``timings``/``samples``."""
    return {
        "schema_version": RESULTS_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": resolve_git_sha(),
        "checkpoint": {"path": checkpoint, "step": step, "revision": revision},
        "subset": {"name": subset_name, "sha256": subset_digest, "n": subset_n},
        "decoding": dict(decoding),
        "judges": dict(judges or {}),
        "environment": {
            "norm_version": NORM_VERSION,
            "metric_libs": metric_lib_versions(),
        },
        "seed": seed,
        "metrics": {},
        "timings_s": {},
    }


def write_results(path: str | Path, results: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        f.write("\n")


def wandb_backfill(
    wandb_run: str,
    metrics: dict,
    step: int,
    audio: dict | None = None,
    sample_rate: int = 24000,
) -> None:
    """Backfill metrics (+ audio) into a training run at its global_step.

    ``wandb_run`` is ``entity/project/run_id``. ``eval/*`` and ``audio/*``
    are define_metric'd against ``global_step`` in the trainer, so these
    points land on the training x-axis at the checkpoint's own step.
    """
    import wandb

    entity, project, run_id = wandb_run.split("/")
    run = wandb.init(entity=entity, project=project, id=run_id, resume="allow")
    payload = dict(metrics)
    payload["global_step"] = step
    for name, wav in (audio or {}).items():
        payload[name] = wandb.Audio(wav, sample_rate=sample_rate)
    run.log(payload)
    run.finish()


def push_results_to_hub(
    paths: list[str],
    repo_id: str,
    dest_prefix: str = "eval",
    token: str | None = None,
    private: bool = True,
) -> None:
    """Publish eval artifacts to the release repo (reuses the trainer's pusher)."""
    from src.training.checkpointing import push_files_to_hub

    push_files_to_hub(
        paths,
        repo_id,
        dest_prefix=dest_prefix,
        token=token,
        private=private,
        commit_message=f"eval results ({dest_prefix})",
    )
