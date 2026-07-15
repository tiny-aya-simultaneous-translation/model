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
                                        FORCED text decode vs the tokenizer-
                                        decoded interleaved reference (LEGACY
                                        keys -- semantics frozen so old
                                        backfills stay comparable)
  eval/gold_{chrfpp,bleu,wer}_tf_{tr2hi,hi2tr}
                                        TF text vs the corpus .pt's GOLD
                                        src/tgt_text (normalized, per
                                        direction; chrF++ primary). CIs in
                                        metrics.json.
  eval/gold_chrfpp_ar_{tr2hi,hi2tr}     free-running AR text (--ar_text) vs
                                        gold refs, over the AR'd samples
  eval/ar_cb0_acc                       greedy AR cb0 reproduction accuracy
  + --audio_samples AR wavs written to --output_dir

Gold references are MT-synthetic (the corpus was machine-translated before
TTS) -- disclose next to any reported number. --subset points at a frozen
eval/subsets/*.jsonl (digest-verified; refuses on drift or missing rows) so
every checkpoint scores the IDENTICAL sample set.

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


def _gold_fields(ds, idx: int) -> dict:
    """Gold text straight from the corpus .pt (src_text/tgt_text, langs).

    The staged corpus carries the TTS input sentences in every .pt (verified
    live 2026-07-15); frozen subsets embed them already -- this is the
    fallback for legacy --num_samples mode.
    """
    p = ds._resolve(ds.rows[idx]["pt_path"])
    try:
        d = torch.load(p, weights_only=False, mmap=True)
    except (TypeError, RuntimeError):
        d = torch.load(p, weights_only=False)
    return {k: d.get(k) for k in ("src_text", "tgt_text", "src_lang", "tgt_lang")}


# direction -> (metric-key suffix, TARGET language for normalization)
_DIR_KEY = {"tr->hi": ("tr2hi", "hi"), "hi->tr": ("hi2tr", "tr")}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--val_jsonl", required=True)
    p.add_argument("--encoded_dir", required=True)
    p.add_argument("--num_samples", type=int, default=200)
    p.add_argument("--subset", default=None,
                   help="frozen eval/subsets/*.jsonl (digest-verified); overrides "
                        "--num_samples/--seed selection")
    p.add_argument("--audio_samples", type=int, default=4, help="samples whose audio is decoded+logged")
    p.add_argument("--ar_audio", action="store_true",
                   help="also AR-generate audio (slow off-TPU; TF audio is the default)")
    p.add_argument("--ar_text", action="store_true",
                   help="with --ar_audio: free-run the text stream too and score it "
                        "against gold refs (eval/gold_chrfpp_ar_*)")
    p.add_argument("--n_bootstrap", type=int, default=1000,
                   help="bootstrap resamples for gold-metric CIs (1 disables)")
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

    # Sample selection: a frozen subset (digest-verified, identical forever)
    # beats the seeded draw -- the draw stays for ad-hoc runs.
    subset_header = None
    if args.subset:
        from src.evaluation.subset import load_subset

        sub_rows, subset_header = load_subset(args.subset)
        by_base = {os.path.basename(r["pt_path"]): i for i, r in enumerate(ds.rows)}
        order, row_metas, missing = [], [], 0
        for r in sub_rows:
            i = by_base.get(os.path.basename(r["pt_path"]))
            if i is None:
                missing += 1
            else:
                order.append(i)
                row_metas.append(r)
        if missing:
            # A shrunken subset silently changes every corpus metric.
            raise SystemExit(
                f"[proxy] REFUSING: {missing}/{len(sub_rows)} subset rows missing "
                f"from this corpus (staging mismatch?)"
            )
        print(
            f"[proxy] subset {subset_header.get('name')} "
            f"sha256={str(subset_header.get('sha256'))[:12]}… n={len(order)}",
            flush=True,
        )
    else:
        g = torch.Generator().manual_seed(args.seed)
        order = torch.randperm(len(ds), generator=g)[: args.num_samples].tolist()
        row_metas = [None] * len(order)

    import sacrebleu
    import soundfile as sf

    from src.data.dataset import undo_codebook_delay
    from src.evaluation.text_metrics import corpus_scores

    MIMI_V = 2048  # everything entering Mimi must be clamped below this

    hyps, refs, ar_cb0_accs = [], [], []
    gold_hyps_tf: dict = {d: [] for d in _DIR_KEY}
    gold_refs_tf: dict = {d: [] for d in _DIR_KEY}
    gold_hyps_ar: dict = {d: [] for d in _DIR_KEY}
    gold_refs_ar: dict = {d: [] for d in _DIR_KEY}
    audio_logs = {}  # wandb.Audio payloads keyed by metric name
    for j, idx in enumerate(order):
        sample = ds[idx]
        meta = row_metas[j]
        if meta is None:
            meta = {**ds.rows[idx], **_gold_fields(ds, idx)}
        direction = meta.get("direction", "")
        gold_ref = meta.get("tgt_text")
        with torch.no_grad():
            pred_codes, text_pred = ec.generate_teacher_forced(
                model, sample, args.device, num_codebooks=8
            )
        tx = ec.text_examination(text_pred, sample, model.backbone.tokenizer)
        hyps.append(tx["text_pred_str"])
        refs.append(tx["text_target_str"])
        if gold_ref and direction in _DIR_KEY:
            gold_hyps_tf[direction].append(tx["text_pred_str"])
            gold_refs_tf[direction].append(gold_ref)

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
                if args.ar_text:
                    gen, ar_text_ids = ec.generate_autoregressive(
                        model, sample, args.device, temp=0.0,
                        free_text=True, return_text=True,
                    )
                    real = ar_text_ids < ec._TEXT_SPECIALS_START
                    ar_str = model.backbone.tokenizer.decode(ar_text_ids[real].tolist())
                    if gold_ref and direction in _DIR_KEY:
                        gold_hyps_ar[direction].append(ar_str)
                        gold_refs_ar[direction].append(gold_ref)
                else:
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

    # Gold-reference metrics: per direction, normalized, chrF++ primary.
    gold_detail: dict = {}
    for d, (suffix, lang) in _DIR_KEY.items():
        if gold_refs_tf[d]:
            sc = corpus_scores(gold_hyps_tf[d], gold_refs_tf[d], lang,
                               n_bootstrap=args.n_bootstrap)
            gold_detail[f"tf_{suffix}"] = sc
            metrics[f"eval/gold_chrfpp_tf_{suffix}"] = sc["chrfpp"]
            metrics[f"eval/gold_bleu_tf_{suffix}"] = sc["bleu"]
            if "wer" in sc:
                metrics[f"eval/gold_wer_tf_{suffix}"] = sc["wer"]
        if gold_refs_ar[d]:
            sc = corpus_scores(gold_hyps_ar[d], gold_refs_ar[d], lang,
                               n_bootstrap=args.n_bootstrap)
            gold_detail[f"ar_{suffix}"] = sc
            metrics[f"eval/gold_chrfpp_ar_{suffix}"] = sc["chrfpp"]

    print(f"[proxy] {json.dumps(metrics, indent=2, ensure_ascii=False)}", flush=True)
    from src.evaluation.normalize import NORM_VERSION

    file_payload = {
        **metrics,
        "gold_detail": gold_detail,
        "norm_version": NORM_VERSION,
        "subset": subset_header,
        "references": "synthetic (machine-translated corpus text)",
    }
    with open(os.path.join(args.output_dir, "metrics.json"), "w") as f:
        json.dump(file_payload, f, indent=2, ensure_ascii=False)

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
