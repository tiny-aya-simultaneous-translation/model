"""Per-checkpoint translation-quality proxy + audio dumps (offline).

WHY OFFLINE: AR decoding has no place inside the locked TPU training loop
(the inline demo covers qualitative audio); this script gives the public
release its quality-vs-tokens curve by evaluating CHECKPOINTS on a CPU/GPU
box and BACKFILLING the metrics into the training W&B run at the
checkpoint's own global_step -- the points land on the same x-axis as the
training curves.

Reuses scripts/eval_checkpoint.py wholesale (self-configuring model load
from the checkpoint's adapter_config, TF/AR generation with the corrected
next-token convention, Mimi decode). Metrics:

  eval/text_bleu_tf, eval/text_chrf_tf  corpus BLEU/chrF of the TEACHER-
                                        FORCED text decode vs reference
                                        (upper-bound proxy; deterministic)
  eval/ar_cb0_acc                       greedy AR cb0 reproduction accuracy
  + --audio_samples AR wavs written to --output_dir

Cadence: run post-hoc over the log-spaced + every-Nth checkpoints (the
watchdog MAY invoke it on a CPU box -- NEVER on the training hosts).

Usage:
  uv run python scripts/eval_translation_proxy.py \
      --checkpoint gs://.../step_005000 \
      --val_jsonl /data/splits/val.jsonl --encoded_dir /data/encoded \
      --num_samples 200 --audio_samples 4 \
      --wandb_run cataluna84/tinyaya-stage2-tpu/<run_id> \
      --output_dir eval_proxy/step_005000
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import scripts.eval_checkpoint as ec  # noqa: E402 - reuse, don't rebuild


def _ckpt_step(checkpoint: str) -> int:
    """The checkpoint's own global step, from metadata.json."""
    uri = os.path.join(checkpoint, "metadata.json")
    if checkpoint.startswith("gs://"):
        raw = subprocess.run(
            ["gsutil", "cat", uri], capture_output=True, text=True
        ).stdout
    else:
        with open(uri) as f:
            raw = f.read()
    return int(json.loads(raw)["step"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--val_jsonl", required=True)
    p.add_argument("--encoded_dir", required=True)
    p.add_argument("--num_samples", type=int, default=200)
    p.add_argument("--audio_samples", type=int, default=4, help="samples whose audio is decoded+logged")
    p.add_argument("--ar_audio", action="store_true",
                   help="also AR-generate audio (slow off-TPU; TF audio is the default)")
    p.add_argument("--output_dir", default="eval_proxy")
    p.add_argument("--device", default="cpu")
    p.add_argument("--wandb_run", default=None, help="entity/project/run_id to backfill")
    p.add_argument("--seed", type=int, default=1337, help="fixed sample selection")
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    step = _ckpt_step(args.checkpoint)
    print(f"[proxy] checkpoint step {step}", flush=True)

    # Model + data via eval_checkpoint's own self-configuring loader (fp32 on
    # CPU: bf16-on-CPU under-reads accuracy -- see its module note).
    ec._AC_DTYPE = torch.float32 if args.device == "cpu" else torch.bfloat16
    model, ds, mimi, rows = ec.load_model_and_data(
        args.checkpoint, args.val_jsonl, args.encoded_dir, args.device
    )

    # Fixed, seeded sample selection => comparable across checkpoints.
    g = torch.Generator().manual_seed(args.seed)
    order = torch.randperm(len(ds), generator=g)[: args.num_samples].tolist()

    import sacrebleu
    import soundfile as sf

    from src.data.dataset import undo_codebook_delay

    MIMI_V = 2048  # everything entering Mimi must be clamped below this

    hyps, refs, ar_cb0_accs = [], [], []
    audio_logs = {}  # wandb.Audio payloads keyed by metric name
    for j, idx in enumerate(order):
        sample = ds[idx]
        with torch.no_grad():
            pred_codes, text_pred = ec.generate_teacher_forced(
                model, sample, args.device, num_codebooks=8
            )
        tx = ec.text_examination(text_pred, sample, model.backbone.tokenizer)
        hyps.append(tx["text_pred_str"])
        refs.append(tx["text_target_str"])

        if j < args.audio_samples:
            src_len = sample["source_length"]
            tgt_len = sample["target_length"]
            # Teacher-forced audio (one forward -- CPU-cheap): the upper-bound
            # demo. pred_codes live in the DELAYED stream space.
            tf_dec = undo_codebook_delay(pred_codes).clamp(0, MIMI_V - 1)
            tf_wav = mimi.decode(tf_dec).numpy()
            src_wav = mimi.decode(
                sample["audio_codes"][:, :src_len].clamp(0, MIMI_V - 1)
            ).numpy()
            tgt_wav = mimi.decode(
                sample["audio_codes"][:, src_len : src_len + tgt_len].clamp(0, MIMI_V - 1)
            ).numpy()
            sf.write(os.path.join(args.output_dir, f"tf_sample_{j}.wav"), tf_wav, 24000)
            audio_logs[f"audio/eval_tf_{j}"] = tf_wav
            audio_logs[f"audio/eval_source_{j}"] = src_wav
            audio_logs[f"audio/eval_target_gt_{j}"] = tgt_wav

            if args.ar_audio:
                gen = ec.generate_autoregressive(model, sample, args.device, temp=0.0)
                gt_cb0 = sample["audio_codes"][0, src_len : src_len + gen.shape[1]]
                n = min(len(gt_cb0), gen.shape[1])
                if n > 0:
                    ar_cb0_accs.append(float((gen[0, :n] == gt_cb0[:n]).float().mean()))
                ar_wav = mimi.decode(
                    undo_codebook_delay(gen).clamp(0, MIMI_V - 1)
                ).numpy()
                sf.write(os.path.join(args.output_dir, f"ar_sample_{j}.wav"), ar_wav, 24000)
                audio_logs[f"audio/eval_ar_{j}"] = ar_wav

        if (j + 1) % 20 == 0:
            print(f"[proxy] {j + 1}/{len(order)} samples", flush=True)

    bleu = sacrebleu.corpus_bleu(hyps, [refs]).score
    chrf = sacrebleu.corpus_chrf(hyps, [refs]).score
    ar_acc = sum(ar_cb0_accs) / len(ar_cb0_accs) if ar_cb0_accs else float("nan")
    metrics = {
        "eval/text_bleu_tf": bleu,
        "eval/text_chrf_tf": chrf,
        "eval/ar_cb0_acc": ar_acc,
        "global_step": step,
    }
    print(f"[proxy] {json.dumps(metrics, indent=2)}", flush=True)
    with open(os.path.join(args.output_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    if args.wandb_run:
        import wandb

        entity, project, run_id = args.wandb_run.split("/")
        run = wandb.init(entity=entity, project=project, id=run_id, resume="allow")
        # eval/* and audio/* are define_metric'd against global_step in the
        # trainer, so these points land on the training x-axis at the
        # checkpoint's own step.
        payload = dict(metrics)
        for name, wav in audio_logs.items():
            payload[name] = wandb.Audio(wav, sample_rate=24000)
        run.log(payload)
        run.finish()
        print(
            f"[proxy] backfilled {len(metrics)} metrics + {len(audio_logs)} audio "
            f"to {args.wandb_run} @ step {step}",
            flush=True,
        )


if __name__ == "__main__":
    main()
