"""LAWA-style uniform checkpoint averaging (the v0.3 Phase-A anti-overfit star).

WHY THIS EXISTS
---------------
The long-horizon v0.3 run keeps EVERY periodic checkpoint (keep_last_n: 0)
precisely so the released model does not have to be a single point on the
trajectory: averaging the last K checkpoints (LAWA) or a window around
``best_by_val`` recovers most of the benefit of a full LR anneal — the
mechanism that rescues an early-stopped run whose schedule never finished
decaying. This script was written for the 2026-07-12 long-horizon plan,
which made it load-bearing.

Method: uniform average of every tensor, accumulated in fp32 and cast back
to the original dtype. Frozen tensors are identical across checkpoints, so
averaging them is the identity — no trainability bookkeeping is needed
(unlike checkpoint_group_rms.py, which must EXCLUDE frozen tensors from
norms). The output directory uses the standard checkpoint layout, so
eval_release.py / export tooling consume it like any other checkpoint. It is
weights-only (no optimizer/scheduler/rng) and is deliberately NOT a resume
target — metadata carries ``save_kind: lawa_average`` and no bare int step.

Usage
-----
  # explicit list
  python scripts/average_checkpoints.py --out /tmp/avg \\
      gs://bucket/run/step_012000 gs://bucket/run/step_013000

  # last K periodic checkpoints of a run
  python scripts/average_checkpoints.py --save-dir gs://bucket/run \\
      --last-k 3 --out gs://bucket/run/lawa_last3

  # K checkpoints nearest to the best_by_val step
  python scripts/average_checkpoints.py --save-dir gs://bucket/run \\
      --around-best 3 --out gs://bucket/run/lawa_best3

CPU-only; ``gs://`` inputs are staged with gcloud storage (optimizer blobs
skipped), a ``gs://`` --out is uploaded with gsutil after local assembly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.training.checkpointing import (  # noqa: E402
    get_checkpoint_dirs,
    read_checkpoint_metadata,
)

_COMPONENT_FILES = (
    "projection.pt",
    "depth_decoder.pt",
    "text_embed.pt",
    "audio_heads.pt",
    "model_audio_embed.pt",
)
_ADAPTER_WEIGHTS = ("adapter_model.safetensors", "adapter_model.bin")


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
            check=False,  # tolerate absent components (e.g. no model_audio_embed)
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


def _load_weights(path: Path) -> dict[str, torch.Tensor]:
    if path.suffix == ".safetensors":
        from safetensors.torch import load_file

        return load_file(str(path))
    return torch.load(path, map_location="cpu", weights_only=True)


def _save_weights(sd: dict[str, torch.Tensor], path: Path) -> None:
    if path.suffix == ".safetensors":
        from safetensors.torch import save_file

        save_file(sd, str(path))
    else:
        torch.save(sd, path)


def _average_file(staged: list[Path], rel: str, out_dir: Path) -> tuple[int, float]:
    """Average one weight file across all staged checkpoints.

    Returns (tensor_count, mean |avg - first| over trainable-scale tensors)
    -- the delta is the sanity signal that averaging actually mixed
    trajectories (0.0 would mean the checkpoints were identical).
    """
    dicts = [_load_weights(d / rel) for d in staged]
    keys = dicts[0].keys()
    for i, sd in enumerate(dicts[1:], 1):
        if sd.keys() != keys:
            raise ValueError(f"{rel}: key mismatch between {staged[0]} and {staged[i]}")
    out: dict[str, torch.Tensor] = {}
    delta_sum, delta_n = 0.0, 0
    for k in keys:
        acc = dicts[0][k].to(torch.float32).clone()
        for sd in dicts[1:]:
            acc += sd[k].to(torch.float32)
        acc /= len(dicts)
        out[k] = acc.to(dicts[0][k].dtype)
        d = (acc - dicts[0][k].to(torch.float32)).abs().mean().item()
        delta_sum += d
        delta_n += 1
    dest = out_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    _save_weights(out, dest)
    return len(out), delta_sum / max(1, delta_n)


def _select_checkpoints(args) -> list[str]:
    if args.checkpoints:
        return args.checkpoints
    if not args.save_dir:
        raise SystemExit("pass checkpoint dirs, or --save-dir with --last-k/--around-best")
    dirs = get_checkpoint_dirs(args.save_dir)
    if not dirs:
        raise SystemExit(f"no complete step_* checkpoints under {args.save_dir}")
    if args.around_best:
        best_meta = read_checkpoint_metadata(args.save_dir.rstrip("/") + "/best_by_val")
        best_step = int(best_meta.get("step", -1))
        if best_step < 0:
            raise SystemExit("--around-best: no readable best_by_val/metadata.json")
        dirs = sorted(dirs, key=lambda d: abs(int(d.rstrip("/").rsplit("step_", 1)[1]) - best_step))
        return sorted(dirs[: args.around_best])
    return dirs[-args.last_k :]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checkpoints", nargs="*", help="explicit checkpoint dirs (local or gs://)")
    ap.add_argument("--save-dir", help="run save_dir to select checkpoints from")
    ap.add_argument("--last-k", type=int, default=3, help="average the last K step_* dirs")
    ap.add_argument("--around-best", type=int, default=0,
                    help="average the K dirs nearest the best_by_val step (overrides --last-k)")
    ap.add_argument("--out", required=True, help="output dir (local or gs://)")
    args = ap.parse_args()

    ckpts = _select_checkpoints(args)
    if len(ckpts) < 2:
        raise SystemExit(f"need >= 2 checkpoints to average, got {ckpts}")
    print(f"[lawa] averaging {len(ckpts)} checkpoints:")
    for c in ckpts:
        print(f"[lawa]   {c}")

    stage_root = Path(tempfile.mkdtemp(prefix="lawa_stage_"))
    staged = [_stage(c, stage_root / f"ck{i}") for i, c in enumerate(ckpts)]

    out_is_gcs = args.out.startswith("gs:")
    out_dir = Path(tempfile.mkdtemp(prefix="lawa_out_")) if out_is_gcs else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for rel in _COMPONENT_FILES:
        if (staged[0] / rel).exists():
            n, delta = _average_file(staged, rel, out_dir)
            print(f"[lawa] {rel}: {n} tensors, mean|avg-first|={delta:.3e}")

    adapter_rel = next(
        (f"peft_adapter/{w}" for w in _ADAPTER_WEIGHTS if (staged[0] / "peft_adapter" / w).exists()),
        None,
    )
    if adapter_rel is None:
        raise SystemExit("no adapter weights found under peft_adapter/")
    n, delta = _average_file(staged, adapter_rel, out_dir)
    print(f"[lawa] {adapter_rel}: {n} tensors, mean|avg-first|={delta:.3e}")
    # adapter config + tokenizer artifacts ride from the LAST (newest) ckpt
    for extra in (staged[-1] / "peft_adapter").iterdir():
        if extra.name not in _ADAPTER_WEIGHTS:
            shutil.copy2(extra, out_dir / "peft_adapter" / extra.name)

    steps = [read_checkpoint_metadata(c).get("step") for c in ckpts]
    meta = {
        "save_kind": "lawa_average",
        "averaged_from": [str(c) for c in ckpts],
        "averaged_steps": steps,
    }
    with open(out_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    if out_is_gcs:
        subprocess.run(
            ["gsutil", "-m", "cp", "-r", str(out_dir).rstrip("/") + "/.", args.out],
            check=True,
        )
        print(f"[lawa] uploaded -> {args.out}")
    else:
        print(f"[lawa] wrote -> {out_dir}")
    shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    main()
