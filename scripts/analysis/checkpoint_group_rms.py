"""Post-hoc per-optimizer-group weight norms (L2 + RMS) from a checkpoint.

WHY THIS EXISTS
---------------
The live ``diag/*`` telemetry (weight/grad RMS, update sizes per optimizer
group) only exists for runs launched after 2026-07-10 — every finished v0.3
arm and probe ran with ``diag_metrics: false``. This script reconstructs the
weight side offline: it loads a saved checkpoint (the component ``.pt`` files
plus the PEFT adapter that ``src/training/checkpointing.py`` writes), maps
every trainable tensor to its optimizer group with the SAME rule the trainer
uses (``src/training/param_classify.classify_param``), and prints per-group
tensor counts, element counts, L2 norm, and RMS = sqrt(mean(p^2)). With the
group lr and the W&B ``train/grad_norm`` series (post-clip global norm ~= 1.0
whenever clipping engaged) that gives the update-to-weight scale the live
telemetry would have shown. Runs on CPU — no TPU, no model construction.

Checkpoint layout expected (see checkpointing.py):
  projection.pt, depth_decoder.pt, text_embed.pt, audio_heads.pt,
  model_audio_embed.pt         -- per-module state dicts (RELATIVE names)
  peft_adapter/adapter_model.safetensors  -- LoRA adapters (self-prefixed)
Component keys are re-prefixed to full-model form before classification so
membership matches ``model.named_parameters()`` exactly.

Trainability is not recorded in state dicts, so the trainer's freeze rules
are mirrored here: the depth decoder contributes only its I/O
(input_projections / embed_tokens / lm_heads) unless ``--depth-unfreeze-blocks
N`` marks the last N transformer blocks trainable (Phase C3), matching
``freeze_depth_internals`` in scripts/train_hierarchical.py.

Usage
-----
  python scripts/analysis/checkpoint_group_rms.py \\
      gs://bucket/checkpoints/run/best_by_val [more ckpt dirs ...] \\
      [--wandb] [--depth-unfreeze-blocks 0]

``gs://`` paths are staged to a temp dir with ``gcloud storage cp`` (the
optimizer/scheduler blobs are skipped — only weights are needed). ``--wandb``
additionally logs one wandb.Table to a fresh run in the training project
(finished runs cannot be appended to, so the analysis gets its own run).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.training.param_classify import classify_param, depth_block_layer_index  # noqa: E402

# Component file -> full-model name prefix, mirroring the module handles in
# checkpointing.save_checkpoint (model.projection, model.depth_decoder,
# model.backbone.{text_embed,audio_heads,model_audio_embed}).
_COMPONENT_PREFIX = {
    "projection.pt": "projection.",
    "depth_decoder.pt": "depth_decoder.",
    "text_embed.pt": "backbone.text_embed.",
    "audio_heads.pt": "backbone.audio_heads.",
    "model_audio_embed.pt": "backbone.model_audio_embed.",
}

# freeze_depth_internals keeps exactly these depth-decoder substrings trainable.
_DEPTH_IO_KEYS = ("input_projections", "embed_tokens", "lm_heads")

# Frozen-base tensors that ride along inside otherwise-trainable containers:
# PEFT saves the full ``embed_tokens.base_layer.weight`` (541M, frozen) in the
# adapter because embed_tokens is a target module, and ``LoRAEmbedding`` keeps
# the frozen original under ``base_embed.`` next to its trainable lora_A/B.
# Both must be excluded or the lora/text_embed groups overcount by ~1.1B.
_FROZEN_MARKERS = ("base_layer", "base_embed")

_N_DEPTH_BLOCKS = 6  # Moshi depth decoder depth (frozen unless Phase C3 unfreezes)


def _stage_gcs(uri: str, dest: Path) -> Path:
    """Copy the weight files of a ``gs://`` checkpoint dir to ``dest``.

    Skips optimizer.pt / scheduler.pt (hundreds of MB, not needed for weight
    norms). Raises CalledProcessError if the copy fails.
    """
    dest.mkdir(parents=True, exist_ok=True)
    uri = uri.rstrip("/")
    for pat in [f"{uri}/metadata.json"] + [f"{uri}/{f}" for f in _COMPONENT_PREFIX]:
        subprocess.run(
            ["gcloud", "storage", "cp", pat, str(dest)],
            check=False,  # tolerate missing components (e.g. no model_audio_embed)
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


def _depth_trainable(name: str, unfreeze_blocks: int) -> bool:
    """Mirror freeze_depth_internals: I/O always, last-N blocks if unfrozen."""
    if any(k in name for k in _DEPTH_IO_KEYS):
        return True
    li = depth_block_layer_index(name)
    return li is not None and unfreeze_blocks > 0 and li >= _N_DEPTH_BLOCKS - unfreeze_blocks


def iter_trainable_tensors(ckpt: Path, depth_unfreeze_blocks: int = 0):
    """Yield ``(full_model_name, tensor)`` for every trainable weight.

    Yields
    ------
    tuple[str, torch.Tensor]
        Full-model parameter name (classify_param-compatible) and its tensor.
    """
    for fname, prefix in _COMPONENT_PREFIX.items():
        path = ckpt / fname
        if not path.exists():
            continue
        state = torch.load(path, map_location="cpu", weights_only=True)
        for k, v in state.items():
            if not torch.is_tensor(v) or not v.is_floating_point():
                continue
            if any(m in k for m in _FROZEN_MARKERS):
                continue
            name = prefix + k
            if fname == "depth_decoder.pt" and not _depth_trainable(name, depth_unfreeze_blocks):
                continue
            yield name, v
    adapter = ckpt / "peft_adapter" / "adapter_model.safetensors"
    if adapter.exists():
        from safetensors.torch import load_file

        for k, v in load_file(str(adapter)).items():
            if any(m in k for m in _FROZEN_MARKERS):
                continue
            # PEFT names carry lora_/lora_embedding markers -> "lora" group.
            yield k, v


def group_stats(ckpt: Path, depth_unfreeze_blocks: int = 0) -> dict[str, dict]:
    """Per-group ``{tensors, numel, l2, rms}`` for one checkpoint dir."""
    acc: dict[str, dict] = defaultdict(lambda: {"tensors": 0, "numel": 0, "sq": 0.0})
    for name, t in iter_trainable_tensors(ckpt, depth_unfreeze_blocks):
        g = classify_param(name)
        acc[g]["tensors"] += 1
        acc[g]["numel"] += t.numel()
        acc[g]["sq"] += float((t.float() ** 2).sum())
    out = {}
    for g, a in sorted(acc.items()):
        out[g] = {
            "tensors": a["tensors"],
            "numel": a["numel"],
            "l2": math.sqrt(a["sq"]),
            "rms": math.sqrt(a["sq"] / max(a["numel"], 1)),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("checkpoints", nargs="+", help="checkpoint dirs (local or gs://)")
    ap.add_argument("--depth-unfreeze-blocks", type=int, default=0)
    ap.add_argument("--wandb", action="store_true", help="log a wandb.Table run")
    ap.add_argument("--wandb-project", default="tinyaya-stage2-tpu")
    ap.add_argument("--wandb-run-name", default="v03-weight-rms-posthoc")
    args = ap.parse_args()

    rows = []
    tmp_root = Path(tempfile.mkdtemp(prefix="ckpt_rms_"))
    try:
        for spec in args.checkpoints:
            label = (
                spec.rstrip("/").split("/")[-2]
                if spec.rstrip("/").endswith("best_by_val")
                else spec.rstrip("/").split("/")[-1]
            )
            if spec.startswith("gs://"):
                ckpt = _stage_gcs(spec, tmp_root / label)
            else:
                ckpt = Path(spec)
            meta = ckpt / "metadata.json"
            step = json.loads(meta.read_text()).get("step") if meta.exists() else None
            stats = group_stats(ckpt, args.depth_unfreeze_blocks)
            print(f"\n=== {label} (step {step}) ===")
            print(f"{'group':<18} {'tensors':>8} {'params':>12} {'L2':>12} {'RMS':>12}")
            for g, s in stats.items():
                print(
                    f"{g:<18} {s['tensors']:>8} {s['numel']:>12,} "
                    f"{s['l2']:>12.4f} {s['rms']:>12.3e}"
                )
                rows.append([label, step, g, s["tensors"], s["numel"], s["l2"], s["rms"]])
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    if args.wandb and rows:
        import wandb

        run = wandb.init(
            project=args.wandb_project,
            name=args.wandb_run_name,
            group="v03-analysis",
            job_type="analysis",
        )
        table = wandb.Table(
            columns=["checkpoint", "step", "group", "tensors", "numel", "l2", "rms"],
            data=rows,
        )
        run.log({"weight_rms_by_group": table})
        run.finish()
        print(f"\nW&B: {run.url}")


if __name__ == "__main__":
    main()
