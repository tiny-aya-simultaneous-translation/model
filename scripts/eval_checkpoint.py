"""Evaluate a TinyAya S2S checkpoint: translation quality + audio quality.

Usage:
    python scripts/eval_checkpoint.py \
        --checkpoint checkpoints/stage2_26k_parallel/best_by_val \
        --val_jsonl /path/to/val_500.jsonl \
        --encoded_dir /path/to/encoded \
        --num_samples 30 \
        --output_dir eval_results/step_3000
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transformers import AutoTokenizer

from src.data.dataset import SILENCE_TOKEN, StreamingTranslationDataset, undo_codebook_delay
from src.data.mimi_encoder import MimiEncoder
from src.model.composite import TinyAyaMoshiComposite
from src.model.lora_setup import apply_lora
from src.training.checkpointing import load_checkpoint

# Compute dtype for the eval forward. Set from --fp32 in main(). On CPU, bf16
# matmuls accumulate in low precision (unlike the TPU MXU's fp32 accumulate), so
# a bf16 CPU eval materially under-reads accuracy vs the on-TPU training metric;
# fp32 on CPU recovers it.
_AC_DTYPE = torch.bfloat16


def _autocast(device):
    dt = device.split(":")[0]
    return torch.amp.autocast(dt, dtype=_AC_DTYPE, enabled=(_AC_DTYPE != torch.float32))


def generate_teacher_forced(model, sample, device, num_codebooks=8):
    """Teacher-forced generation — upper bound on quality.

    Returns
    -------
    (pred_codes, text_pred) : tuple[torch.Tensor, torch.Tensor]
        ``pred_codes`` [8, tgt_len] argmax audio codes in DELAYED space;
        ``text_pred`` [tgt_len] argmax next-token TEXT ids over the same
        target region (same shift convention as the audio prediction and the
        training text loss).
    """
    T = sample["text_ids"].shape[0]
    src_len = sample["source_length"]

    user_cb0 = sample["user_audio_codes"][0].unsqueeze(0).to(device)
    model_cb0 = sample["model_audio_codes"][0].unsqueeze(0).to(device)
    text = sample["text_ids"].unsqueeze(0).to(device)
    mask = torch.ones(1, T, dtype=torch.long, device=device)
    full_model = sample["model_audio_codes"].unsqueeze(0).to(device)

    with torch.no_grad(), _autocast(device):
        output = model(
            text_ids=text, audio_codes=user_cb0, model_audio_codes=model_cb0,
            attention_mask=mask, full_audio_codes=full_model[:, :num_codebooks, :],
            depth_chunk_size=16,
        )
        text_logits, audio_logits, _ = output

    # Next-token predictions for target region
    pred_codes = audio_logits[0, :, src_len - 1:-1, :].argmax(dim=-1)  # [8, tgt_len]
    text_pred = text_logits[0, src_len - 1:-1, :].argmax(dim=-1)  # [tgt_len]
    return pred_codes.cpu(), text_pred.cpu()


# The interleaver's 4 frame-padding specials occupy ids >= TEXT_PADDING; real
# text tokens are strictly below. Accuracy counted over padding positions
# would read ~100% on a text stream that never learned a word.
_TEXT_SPECIALS_START = 262144


def text_examination(text_pred, sample, tokenizer):
    """Text-stream TF accuracy (real tokens only) + decoded strings.

    Mirrors train_hierarchical's ``val/text_acc`` masking: only target-region
    positions whose GROUND-TRUTH token is a real text id (< 262144) count.

    Returns
    -------
    dict with ``text_acc`` (float; -1.0 when the sample has no real text
    tokens), ``text_target_str``, ``text_pred_str`` (tokenizer-decoded, real
    positions only, prediction read at the same positions as the target).
    """
    src_len = sample["source_length"]
    tgt_text = sample["text_ids"][src_len:src_len + text_pred.shape[0]]
    real = tgt_text < _TEXT_SPECIALS_START
    n_real = int(real.sum())
    if n_real == 0:
        return {"text_acc": -1.0, "text_target_str": "", "text_pred_str": ""}
    acc = float((text_pred[real] == tgt_text[real]).float().mean())
    target_str = tokenizer.decode(tgt_text[real].tolist())
    # Read the prediction at the SAME positions so the two strings align
    # word-for-word; clamp any (wrong) special-id prediction into vocab range
    # for decodability -- it still counts as a miss in text_acc.
    pred_ids = text_pred[real].clamp(max=_TEXT_SPECIALS_START - 1)
    pred_str = tokenizer.decode(pred_ids.tolist())
    return {"text_acc": acc, "text_target_str": target_str, "text_pred_str": pred_str}


def generate_autoregressive(
    model, sample, device, temp=0.8, top_p=0.9, free_text=False, return_text=False
):
    """Autoregressive generation — realistic quality.

    ``free_text=True`` additionally free-runs the TEXT stream (greedy argmax
    from the backbone's text head at each frame) instead of teacher-forcing
    the gold interleaved text — the honest AR text-translation mode used by
    the evals program's gold-reference metrics. ``return_text=True`` returns
    ``(codes, text_ids_of_target_region)`` instead of just codes; defaults
    preserve the original behavior for existing callers.

    NEXT-TOKEN CONVENTION (the off-by-one this gate caught, 2026-07-09)
    -------------------------------------------------------------------
    Training computes ``pred = logits[:, :-1]`` vs ``target[:, 1:]``: the
    hidden state at position ``t-1`` predicts the token AT ``t``. So to
    generate position ``t`` the backbone must run over the clean prefix
    ``[:, :t]`` (positions ``0..t-1``) and the head reads ``hidden[:, -1]``
    (= position ``t-1``). The original loop ran over ``[:, :t+1]`` — one
    position too far: it read the hidden AT ``t`` (whose input was still the
    SILENCE placeholder) and wrote the resulting ``t+1`` prediction at ``t``.
    Result: every token shifted one frame + conditioned on a placeholder —
    ~2-5% reproduction on a fully memorized sample (TF 100%) until fixed.
    """
    T = sample["text_ids"].shape[0]
    src_len = sample["source_length"]

    user_stream = sample["user_audio_codes"][0].unsqueeze(0).to(device)
    model_stream = torch.full((1, T), SILENCE_TOKEN, dtype=torch.long, device=device)
    ar_text = sample["text_ids"].unsqueeze(0).to(device).clone()
    gen_all = torch.full((8, T), SILENCE_TOKEN, dtype=torch.long, device=device)

    for t in range(src_len, T):
        ar_mask = torch.ones(1, t, dtype=torch.long, device=device)

        with torch.no_grad(), _autocast(device):
            bb_out = model.backbone(
                text_ids=ar_text[:, :t],
                audio_codes=user_stream[:, :t],
                model_audio_codes=model_stream[:, :t],
                attention_mask=ar_mask,
            )
            hidden = bb_out["hidden_states"]

            if free_text:
                # Same next-token convention as audio: hidden[-1] (position
                # t-1) predicts the text token AT t; the write lands before
                # any later iteration reads position t. Greedy — the text
                # stream is deterministic even when audio samples.
                ar_text[0, t] = bb_out["text_logits"][0, -1].argmax(dim=-1)

            # CB0 from backbone
            cb0_logits = model.backbone.audio_heads[0](hidden[:, -1:, :]).squeeze()
            cb0_tok = _sample_top_p(cb0_logits, temp, top_p)
            model_stream[0, t] = cb0_tok
            gen_all[0, t] = cb0_tok

            # CB1-7 from depth decoder
            projected = model.projection(hidden[:, -1:, :])
            ctx_expanded = projected.expand(1, model.num_codebooks, -1).contiguous()
            depth_input = torch.zeros(1, model.num_codebooks, dtype=torch.long, device=device)
            depth_input[0, 1] = cb0_tok

            depth_out = model.depth_decoder(
                input_ids=depth_input, last_hidden_state=ctx_expanded,
                use_cache=False, return_dict=True,
            )

            for cb_idx in range(7):
                logits = depth_out.logits[0, cb_idx + 1, :].float()
                tok = _sample_top_p(logits, temp, top_p)
                gen_all[cb_idx + 1, t] = tok
                if cb_idx + 2 < model.num_codebooks:
                    depth_input[0, cb_idx + 2] = tok

    if return_text:
        return gen_all[:, src_len:T].cpu(), ar_text[0, src_len:T].cpu()
    return gen_all[:, src_len:T].cpu()


def _sample_top_p(logits, temp, top_p):
    # temp<=0 -> greedy (argmax). For a memorization-reproduction check we want
    # deterministic decoding so a perfectly-learned model reproduces the target.
    if temp <= 0:
        return logits.argmax(dim=-1)
    probs = torch.softmax(logits.float() / temp, dim=-1)
    sorted_p, sorted_i = torch.sort(probs, descending=True)
    cum = torch.cumsum(sorted_p, dim=-1)
    mask = cum - sorted_p > top_p
    sorted_p[mask] = 0.0
    sorted_p = sorted_p / sorted_p.sum()
    return sorted_i[torch.multinomial(sorted_p, 1)].squeeze(-1)


def run_asr(audio_path, model_size="large-v3", language=None):
    """Run Whisper ASR on audio file, return transcript."""
    from faster_whisper import WhisperModel
    if not hasattr(run_asr, "_model"):
        print(f"  Loading Whisper {model_size}...", flush=True)
        run_asr._model = WhisperModel(model_size, device="cuda", compute_type="float16")
    segments, info = run_asr._model.transcribe(audio_path, language=language, beam_size=5)
    return " ".join(s.text.strip() for s in segments)


def compute_bleu(hypothesis, reference):
    """Simple corpus BLEU (sacrebleu-style)."""
    try:
        import sacrebleu
        result = sacrebleu.sentence_bleu(hypothesis, [reference])
        return result.score
    except ImportError:
        # Fallback: simple unigram precision
        hyp_tokens = hypothesis.lower().split()
        ref_tokens = reference.lower().split()
        if not hyp_tokens:
            return 0.0
        matches = sum(1 for t in hyp_tokens if t in ref_tokens)
        return (matches / len(hyp_tokens)) * 100


def load_model_and_data(checkpoint, val_jsonl, encoded_dir, device, lora_r_fallback=16):
    """Self-configuring checkpoint loader shared by this eval and
    eval_translation_proxy.py.

    Builds the LoRA structure from the checkpoint's OWN adapter_config.json
    (target_modules / r / alpha / rslora) rather than hardcoding it --
    otherwise the adapter's weights for any module the eval didn't wrap
    (e.g. the +MLP k/o/gate/up/down at r=32) silently fail to load and the
    model runs mostly-untrained. Adapter LAYOUT must also match exactly:
    scan_homogeneous checkpoints (layers_to_transform == null) carry adapters
    on ALL 36 layers, and an eval model built with the classic exclude_top=2
    (34 layers) would silently DROP the top-2 tensors as "unexpected" keys.

    Returns (model.eval() on device, dataset, mimi decoder, val rows).
    """
    print("Loading model...", flush=True)
    _acfg_uri = os.path.join(checkpoint, "peft_adapter", "adapter_config.json")
    if checkpoint.startswith("gs://"):
        import subprocess as _sp
        _acfg = json.loads(_sp.run(["gsutil", "cat", _acfg_uri], capture_output=True, text=True).stdout)
    else:
        with open(_acfg_uri) as _f:
            _acfg = json.load(_f)
    _r = _acfg.get("r", lora_r_fallback)
    _ltt = _acfg.get("layers_to_transform")
    _scan_homog = _ltt is None
    _excl = 0 if _scan_homog else max(0, 36 - len(_ltt))
    print(f"  LoRA from checkpoint: r={_r} alpha={_acfg.get('lora_alpha')} "
          f"rslora={_acfg.get('use_rslora')} targets={_acfg.get('target_modules')} "
          f"layout={'ALL-36 (scan_homogeneous)' if _scan_homog else f'0..{35 - _excl}'}",
          flush=True)
    model = TinyAyaMoshiComposite(num_codebooks=8)
    model.backbone = apply_lora(
        model.backbone,
        r=_r,
        lora_alpha=_acfg.get("lora_alpha", 2 * _r),
        target_modules=_acfg.get("target_modules"),
        use_rslora=_acfg.get("use_rslora", False),
        num_full_ft_layers=0,
        lora_exclude_top=_excl,
        scan_homogeneous=_scan_homog,
    )
    load_checkpoint(model, None, None, checkpoint)
    model = model.to(device).to(_AC_DTYPE).eval()

    tokenizer = AutoTokenizer.from_pretrained("CohereLabs/tiny-aya-base", trust_remote_code=True)
    ds = StreamingTranslationDataset(val_jsonl, tokenizer, max_frames=300, encoded_dir=encoded_dir)
    mimi = MimiEncoder(device=device)
    with open(val_jsonl) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return model, ds, mimi, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--val_jsonl", required=True)
    parser.add_argument("--encoded_dir", required=True)
    parser.add_argument("--num_samples", type=int, default=30)
    parser.add_argument("--output_dir", default="eval_results")
    parser.add_argument("--whisper_model", default="large-v3")
    parser.add_argument("--skip_ar", action="store_true", help="Skip slow autoregressive generation")
    parser.add_argument("--skip_asr", action="store_true", help="Skip Whisper ASR/BLEU (audio-only sanity)")
    parser.add_argument("--device", default="cuda", help="cuda | cpu (xla not supported for the AR loop)")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank of the checkpoint (must match)")
    parser.add_argument("--ar_temp", type=float, default=0.0, help="AR sampling temp; 0 = greedy (reproduction check)")
    parser.add_argument("--ar_top_p", type=float, default=0.9)
    parser.add_argument("--fp32", action="store_true", help="Run the forward in fp32 (recommended on CPU; bf16-on-CPU under-reads accuracy)")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    device = args.device
    global _AC_DTYPE
    _AC_DTYPE = torch.float32 if args.fp32 else torch.bfloat16

    model, ds, mimi, rows = load_model_and_data(
        args.checkpoint, args.val_jsonl, args.encoded_dir, device, lora_r_fallback=args.lora_r
    )
    tokenizer = model.backbone.tokenizer

    num_samples = min(args.num_samples, len(ds))
    results = []

    for i in range(num_samples):
        print(f"\n{'='*60}", flush=True)
        print(f"Sample {i+1}/{num_samples}", flush=True)

        sample = ds[i]
        row = rows[i]
        src_len = sample["source_length"]
        tgt_len = sample["target_length"]
        direction = row.get("direction", "unknown")

        # Determine target language for ASR
        tgt_lang = "hi" if "hi" in direction.split("->")[-1] else "tr"

        sample_dir = os.path.join(args.output_dir, f"sample_{i:03d}")
        os.makedirs(sample_dir, exist_ok=True)

        # Decode source + ground truth
        raw_audio = sample["audio_codes"]
        src_wav = mimi.decode(raw_audio[:, :src_len]).numpy()
        tgt_wav = mimi.decode(raw_audio[:, src_len:]).numpy()
        sf.write(os.path.join(sample_dir, "source.wav"), src_wav, 24000)
        sf.write(os.path.join(sample_dir, "target_gt.wav"), tgt_wav, 24000)

        # Teacher-forced generation
        t0 = time.time()
        tf_codes, text_pred = generate_teacher_forced(model, sample, device)
        text_exam = text_examination(text_pred, sample, tokenizer)
        # tf_codes are in the DELAYED codebook space (the model predicts the
        # delayed model_audio_codes). Undo the per-codebook delay before Mimi
        # decode so every codebook is temporally realigned -- decoding delayed
        # codes directly garbles the audio. (undo_codebook_delay was imported
        # but never applied.) clamp SILENCE(2048)->2047 AFTER undo.
        tf_codes_clean = undo_codebook_delay(tf_codes).clamp(max=2047)
        tf_wav = mimi.decode(tf_codes_clean.to(device)).numpy()
        sf.write(os.path.join(sample_dir, "teacher_forced.wav"), tf_wav, 24000)
        tf_time = time.time() - t0

        # Per-codebook accuracy (teacher-forced)
        gt_delayed = sample["model_audio_codes"][:, src_len:src_len + tf_codes.shape[1]]
        cb_accs = []
        for cb in range(8):
            acc = (tf_codes[cb] == gt_delayed[cb]).float().mean().item()
            cb_accs.append(acc)

        # Autoregressive generation
        ar_wav = None
        ar_time = 0
        ar_per_cb_match = None
        if not args.skip_ar:
            t0 = time.time()
            ar_codes = generate_autoregressive(model, sample, device, temp=args.ar_temp, top_p=args.ar_top_p)
            # AR output is likewise in DELAYED space -- undo before decode.
            ar_codes_clean = undo_codebook_delay(ar_codes).clamp(max=2047)
            ar_wav = mimi.decode(ar_codes_clean.to(device)).numpy()
            sf.write(os.path.join(sample_dir, "autoregressive.wav"), ar_wav, 24000)
            ar_time = time.time() - t0
            # AR reproduction rate: exact match vs the ground-truth DELAYED
            # codes (same comparison as the TF accuracy above). On a memorized
            # sample with greedy decoding, CB0 match should approach the TF
            # acc; a large TF->AR gap = generation-path bug (feedback /
            # delay / depth seeding), invisible to TF metrics.
            ar_gt = sample["model_audio_codes"][:, src_len:src_len + ar_codes.shape[1]]
            ar_per_cb_match = [
                (ar_codes[cb] == ar_gt[cb]).float().mean().item() for cb in range(8)
            ]

        # ASR on generated audio (skippable -- Whisper is CUDA-oriented + slow;
        # for an audio-only reproduction sanity check the per-codebook accuracy
        # and the decoded waveforms are enough).
        gt_transcript = tf_transcript = ar_transcript = ""
        tf_bleu = ar_bleu = 0.0
        if not args.skip_asr:
            print("  Running ASR...", flush=True)
            gt_transcript = run_asr(os.path.join(sample_dir, "target_gt.wav"), args.whisper_model, language=tgt_lang)
            tf_transcript = run_asr(os.path.join(sample_dir, "teacher_forced.wav"), args.whisper_model, language=tgt_lang)
            ar_transcript = run_asr(os.path.join(sample_dir, "autoregressive.wav"), args.whisper_model, language=tgt_lang) if ar_wav is not None else ""
            tf_bleu = compute_bleu(tf_transcript, gt_transcript)
            ar_bleu = compute_bleu(ar_transcript, gt_transcript) if ar_transcript else 0.0

        result = {
            "sample_idx": i,
            "direction": direction,
            "src_frames": src_len,
            "tgt_frames": tgt_len,
            "cb0_acc": cb_accs[0],
            "cb_avg_acc": np.mean(cb_accs),
            "per_cb_acc": cb_accs,
            "text_acc": text_exam["text_acc"],
            "text_target_str": text_exam["text_target_str"],
            "text_pred_str": text_exam["text_pred_str"],
            "ar_per_cb_match": ar_per_cb_match,
            "tf_bleu": tf_bleu,
            "ar_bleu": ar_bleu,
            "gt_transcript": gt_transcript,
            "tf_transcript": tf_transcript,
            "ar_transcript": ar_transcript,
            "tf_time": tf_time,
            "ar_time": ar_time,
        }
        results.append(result)

        print(f"  Direction: {direction}", flush=True)
        print(f"  CB0 acc: {cb_accs[0]*100:.1f}%, Avg: {np.mean(cb_accs)*100:.1f}%", flush=True)
        if text_exam["text_acc"] >= 0:
            print(f"  TEXT acc: {text_exam['text_acc']*100:.1f}% (real tokens)", flush=True)
            print(f"  TEXT tgt:  {text_exam['text_target_str'][:100]}", flush=True)
            print(f"  TEXT pred: {text_exam['text_pred_str'][:100]}", flush=True)
        else:
            print("  TEXT: no real text tokens in target region (audio-only sample)", flush=True)
        if ar_per_cb_match is not None:
            print(
                f"  AR reproduction (greedy vs GT): cb0={ar_per_cb_match[0]*100:.1f}% "
                f"avg={np.mean(ar_per_cb_match)*100:.1f}% "
                "(AR text is teacher-forced by design)",
                flush=True,
            )
        print(f"  GT:  {gt_transcript[:80]}", flush=True)
        print(f"  TF:  {tf_transcript[:80]}", flush=True)
        print(f"  AR:  {ar_transcript[:80]}", flush=True)
        print(f"  BLEU — TF: {tf_bleu:.1f}, AR: {ar_bleu:.1f}", flush=True)

    # Summary
    print(f"\n{'='*60}", flush=True)
    print(f"SUMMARY ({num_samples} samples)", flush=True)
    print(f"{'='*60}", flush=True)
    avg_cb0 = np.mean([r["cb0_acc"] for r in results])
    avg_cb_all = np.mean([r["cb_avg_acc"] for r in results])
    avg_tf_bleu = np.mean([r["tf_bleu"] for r in results])
    avg_ar_bleu = np.mean([r["ar_bleu"] for r in results])
    _text_accs = [r["text_acc"] for r in results if r["text_acc"] >= 0]
    avg_text_acc = float(np.mean(_text_accs)) if _text_accs else -1.0
    _ar_matches = [r["ar_per_cb_match"] for r in results if r["ar_per_cb_match"]]
    avg_ar_cb0 = float(np.mean([m[0] for m in _ar_matches])) if _ar_matches else -1.0
    avg_ar_all = float(np.mean([np.mean(m) for m in _ar_matches])) if _ar_matches else -1.0
    print(f"  Avg CB0 accuracy:     {avg_cb0*100:.1f}%", flush=True)
    print(f"  Avg all-CB accuracy:  {avg_cb_all*100:.1f}%", flush=True)
    if avg_text_acc >= 0:
        print(f"  Avg TEXT accuracy:    {avg_text_acc*100:.1f}% ({len(_text_accs)} samples w/ text)", flush=True)
    if avg_ar_cb0 >= 0:
        print(f"  Avg AR reproduction:  cb0={avg_ar_cb0*100:.1f}% all-CB={avg_ar_all*100:.1f}%", flush=True)
    print(f"  Avg TF BLEU:          {avg_tf_bleu:.1f}", flush=True)
    print(f"  Avg AR BLEU:          {avg_ar_bleu:.1f}", flush=True)

    # Save results
    with open(os.path.join(args.output_dir, "results.json"), "w") as f:
        json.dump({"summary": {"avg_cb0_acc": avg_cb0, "avg_cb_all_acc": avg_cb_all,
                                "avg_text_acc": avg_text_acc,
                                "avg_ar_cb0_match": avg_ar_cb0,
                                "avg_ar_all_cb_match": avg_ar_all,
                                "avg_tf_bleu": avg_tf_bleu, "avg_ar_bleu": avg_ar_bleu,
                                "num_samples": num_samples},
                   "samples": results}, f, indent=2)
    print(f"\nResults saved to {args.output_dir}/results.json", flush=True)


if __name__ == "__main__":
    main()
