"""Capacity report: trainable params x dataset tokens for the v0.3 reval arms.

WHY THIS EXISTS
---------------
The v0.3 recipe was frozen from a 1,500-step / 200K-subset sweep; before the
full-corpus long-horizon run, six recipe arms were re-validated at a
5,000-step horizon. Picking LoRA rank without
knowing the tokens-per-trainable-parameter budget is guesswork, so this script
prints, per arm: the analytic trainable-parameter breakdown (backbone LoRA,
embedding adapters, always-trainable heads, depth-decoder I/O) and the
supervised-token budget over the planned horizon -- the "is r=64 oversized /
is r=16 starved" number.

Everything is closed-form arithmetic from the model configs; no weights are
downloaded and no TPU is touched. The one empirical input is the mean frame
count per utterance, measured from a sample of encoded ``.pt`` files
(``--pt-dir``) or supplied via ``--avg-frames``.

Cross-check: at the v0.2-era config (r=16, targets q,v,embed, exclude_top=2)
this reconciles with the live-run audit of 2026-06-24 (122M trainable,
5.17B composite) to within ~1M; the depth-decoder I/O constant below is the
residual of that audit. The training script prints the exact count at startup
(``freeze_depth_internals`` + the "Total .. trainable .." line) -- treat that
as ground truth and this report as the planning estimate.
"""

import argparse
import json
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Model dimensions.
#
# Backbone numbers come from CohereLabs/tiny-aya-base config.json (verified
# 2026-07-07); depth-decoder numbers from src/model/depth_decoder.py
# create_depth_decoder() defaults. Baked in so the report runs offline; if the
# backbone repo ever changes, re-verify against the HF config.
# ---------------------------------------------------------------------------
HIDDEN = 2048
N_LAYERS = 36
N_HEADS = 16
N_KV_HEADS = 4
HEAD_DIM = 128
FFN = 11008
TEXT_VOCAB = 262_144  # tiny-aya-base vocab
NUM_SPECIAL = 4  # backbone.py: EPAD/BOS-style special ids
AUDIO_VOCAB = 2048
NUM_CODEBOOKS = 8
RESIZED_VOCAB = TEXT_VOCAB + NUM_SPECIAL + AUDIO_VOCAB  # 264,196 (embed_tokens)
TEXT_EMBED_ROWS = TEXT_VOCAB + NUM_SPECIAL  # 262,148 (LoRAEmbedding)

Q_OUT = N_HEADS * HEAD_DIM  # 2048
KV_OUT = N_KV_HEADS * HEAD_DIM  # 512

# Always-trainable backbone-side components (see apply_lora + composite.py):
AUDIO_HEADS = NUM_CODEBOOKS * HIDDEN * AUDIO_VOCAB  # 8 x Linear(2048->2048)
MODEL_AUDIO_EMBED = (AUDIO_VOCAB + 1) * HIDDEN  # +1 silence token
PROJECTION = HIDDEN * 4096 + 4096  # bridge to depth input

# CAVEAT (dead trainable capacity): apply_lora flips requires_grad=True on ALL 8
# audio_heads, so the 122M audit and AUDIO_HEADS above count all of them. But the
# composite forward only consumes audio_heads[0] (composite.py:352 -> CB0); it
# discards backbone.forward's stacked audio_logits (composite.py:274-275) and
# derives CB1-7 from the depth decoder. So audio_heads[1:8] never reach the loss
# and receive no gradient -- ~29M trainable-but-dead params. EFFECTIVE_AUDIO_HEADS
# is the head[0]-only count actually trained; the report prints both so the
# tokens/param budget can be read against real, not nominal, capacity.
EFFECTIVE_AUDIO_HEADS = HIDDEN * AUDIO_VOCAB  # head[0] only
DEAD_AUDIO_HEADS = AUDIO_HEADS - EFFECTIVE_AUDIO_HEADS  # heads[1:8], no gradient

# Depth-decoder trainable I/O (input_projections + embed_tokens + lm_heads,
# per freeze_depth_internals). Analytic reconstruction of the Moshi
# FlexibleLinear shapes is fragile, so we use the residual of the 2026-06-24
# live audit: 122M total - 58.25M accounted = ~63.75M. Exact value is printed
# by freeze_depth_internals at every run start.
DEPTH_IO = 63_750_000

# Depth transformer blocks total ~617M over 6 layers (measured on the TPU
# smoke, see freeze_depth_internals comment) -> per-block estimate for the
# depth_unfreeze_blocks arm.
DEPTH_BLOCKS_TOTAL = 617_000_000
DEPTH_N_BLOCKS = 6

# LoRA parameter cost per adapted module: A(r x in) + B(out x r).
_MODULE_IO = {
    "q_proj": (HIDDEN, Q_OUT),
    "k_proj": (HIDDEN, KV_OUT),
    "v_proj": (HIDDEN, KV_OUT),
    "o_proj": (Q_OUT, HIDDEN),
    "gate_proj": (HIDDEN, FFN),
    "up_proj": (HIDDEN, FFN),
    "down_proj": (FFN, HIDDEN),
}

PLUS_MLP_TARGETS = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
    "embed_tokens",
]


def lora_params(r: int, target_modules: list[str], exclude_top: int) -> int:
    """Analytic LoRA parameter count for the backbone adapter set.

    Args:
        r: LoRA rank.
        target_modules: PEFT target module names; ``embed_tokens`` adapts the
            resized (264,196-row) input embedding once (not per layer).
        exclude_top: top layers excluded from per-layer adapters
            (``apply_lora`` freezes them).

    Returns:
        Total adapter parameters, including the separate ``LoRAEmbedding``
        wrap of ``backbone.text_embed`` that ``apply_lora`` always applies.
    """
    layers = N_LAYERS - exclude_top
    per_layer = sum(r * (i + o) for name, (i, o) in _MODULE_IO.items() if name in target_modules)
    total = layers * per_layer
    if "embed_tokens" in target_modules:
        total += r * (RESIZED_VOCAB + HIDDEN)  # PEFT lora.Embedding
    total += r * (TEXT_EMBED_ROWS + HIDDEN)  # LoRAEmbedding(text_embed)
    return total


def fixed_trainables(depth_unfreeze_blocks: int = 0, effective: bool = False) -> int:
    """Non-LoRA trainable params: heads, embeds, projection, depth I/O.

    Args:
        depth_unfreeze_blocks: last-N depth transformer blocks unfrozen
            (arm F); estimated at DEPTH_BLOCKS_TOTAL / 6 per block.
        effective: if True, count only audio_heads[0] (the head that reaches
            the loss) instead of all 8 -- i.e. real, not nominal, capacity.

    Returns:
        Parameter count that is trainable regardless of LoRA rank. With
        ``effective=False`` this matches the optimizer's requires_grad count
        (and the 2026-06-24 audit); with ``effective=True`` it excludes the
        ~29M dead audio_heads[1:8].
    """
    heads = EFFECTIVE_AUDIO_HEADS if effective else AUDIO_HEADS
    n = heads + MODEL_AUDIO_EMBED + PROJECTION + DEPTH_IO
    n += depth_unfreeze_blocks * DEPTH_BLOCKS_TOTAL // DEPTH_N_BLOCKS
    return n


def measure_avg_frames(pt_dir: Path, sample: int, seed: int = 0) -> tuple[float, int]:
    """Mean frame count from a random sample of encoded ``.pt`` files.

    Args:
        pt_dir: directory of Mimi-encoded ``.pt`` files (tensors shaped
            ``[codebooks, T]`` or dicts holding them).
        sample: number of files to load.
        seed: sampling seed.

    Returns:
        ``(mean_frames, n_measured)``. Frame = one Mimi step (12.5 Hz), the
        unit of CB0 supervision on the backbone.

    Notes:
        Imports torch lazily so the analytic report works without it.
    """
    import torch

    files = sorted(pt_dir.glob("*.pt"))
    if not files:
        raise FileNotFoundError(f"no .pt files under {pt_dir}")
    random.Random(seed).shuffle(files)
    frames = []
    for f in files[:sample]:
        obj = torch.load(f, map_location="cpu", weights_only=False)
        # encode stage stores either a bare [K, T] LongTensor or a dict of
        # per-side tensors; count the target-side (or only) code tensor.
        tensors = obj.values() if isinstance(obj, dict) else [obj]
        for t in tensors:
            if hasattr(t, "dim") and t.dim() >= 2:
                frames.append(t.shape[-1])
                break
    if not frames:
        raise ValueError(f"no [K, T] code tensors found in sample from {pt_dir}")
    return sum(frames) / len(frames), len(frames)


ARMS = [
    # (name, r, targets, exclude_top, depth_unfreeze, note)
    ("A r32 champion", 32, PLUS_MLP_TARGETS, 2, 0, "frozen winner"),
    ("B r64", 64, PLUS_MLP_TARGETS, 2, 0, "capacity-up"),
    ("C r16", 16, PLUS_MLP_TARGETS, 2, 0, "capacity-down"),
    ("D excl_top=0", 32, PLUS_MLP_TARGETS, 0, 0, "full-depth LoRA"),
    ("E regularized", 32, PLUS_MLP_TARGETS, 2, 0, "same params as A"),
    ("F depth_unfreeze=2", 32, PLUS_MLP_TARGETS, 2, 2, "CB1-7 capacity"),
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--train-samples", type=int, default=1_178_302, help="train-split size (v0.3 full corpus)"
    )
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument(
        "--pt-dir", type=Path, default=None, help="measure avg frames from encoded .pt files here"
    )
    p.add_argument("--sample", type=int, default=200)
    p.add_argument(
        "--avg-frames",
        type=float,
        default=None,
        help="override mean frames/utterance (skips --pt-dir)",
    )
    p.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = p.parse_args()

    if args.avg_frames is not None:
        avg_frames, n_meas, src = args.avg_frames, 0, "override"
    elif args.pt_dir is not None:
        avg_frames, n_meas = measure_avg_frames(args.pt_dir, args.sample)
        src = f"measured n={n_meas}"
    else:
        # 300-frame cap = 24 s; typical TTS sentence is well under it. This
        # default is an ASSUMPTION -- pass --pt-dir for a real measurement.
        avg_frames, n_meas, src = 125.0, 0, "ASSUMED (pass --pt-dir to measure)"

    # Supervision budget. CB0 tokens land on the backbone(+LoRA) path; the
    # other 7 codebooks are predicted by the depth path (I/O + optional
    # unfrozen blocks), so both budgets are reported.
    cb0_per_epoch = args.train_samples * avg_frames
    all_per_epoch = cb0_per_epoch * NUM_CODEBOOKS
    horizon_cb0 = cb0_per_epoch * args.epochs
    horizon_all = all_per_epoch * args.epochs

    rows = []
    for name, r, targets, excl, dunf, note in ARMS:
        lp = lora_params(r, targets, excl)
        fixed = fixed_trainables(dunf)
        eff_fixed = fixed_trainables(dunf, effective=True)
        total = lp + fixed
        eff_total = lp + eff_fixed
        rows.append(
            {
                "arm": name,
                "r": r,
                "exclude_top": excl,
                "depth_unfreeze_blocks": dunf,
                "lora_params": lp,
                "fixed_params": fixed,
                "trainable_total": total,
                "effective_total": eff_total,  # excludes dead audio_heads[1:8]
                # CB0 supervision trains the backbone LoRA path; this ratio is
                # the direct "is rank r starved/oversized" signal.
                "cb0_tokens_per_lora_param": horizon_cb0 / lp,
                "cb0_tokens_per_param": horizon_cb0 / total,
                "all_tokens_per_param": horizon_all / total,
                "note": note,
            }
        )

    if args.json:
        print(
            json.dumps(
                {
                    "avg_frames": avg_frames,
                    "frames_source": src,
                    "train_samples": args.train_samples,
                    "epochs": args.epochs,
                    "cb0_tokens_horizon": horizon_cb0,
                    "all_tokens_horizon": horizon_all,
                    "arms": rows,
                },
                indent=2,
            )
        )
        return

    print(f"avg frames/utterance: {avg_frames:.1f}  ({src})")
    print(f"train samples: {args.train_samples:,}   epochs: {args.epochs:g}")
    print(f"CB0 tokens over horizon:  {horizon_cb0 / 1e6:,.0f}M")
    print(f"all-CB tokens over horizon: {horizon_all / 1e6:,.0f}M")
    print()
    hdr = (
        f"{'arm':<20} {'LoRA':>8} {'fixed':>8} {'total':>8} "
        f"{'CB0/LoRA':>9} {'CB0 tok/p':>10} {'allCB tok/p':>11}  note"
    )
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        print(
            f"{row['arm']:<20} {row['lora_params'] / 1e6:>7.1f}M "
            f"{row['fixed_params'] / 1e6:>7.1f}M "
            f"{row['trainable_total'] / 1e6:>7.1f}M "
            f"{row['cb0_tokens_per_lora_param']:>9.1f} "
            f"{row['cb0_tokens_per_param']:>10.2f} "
            f"{row['all_tokens_per_param']:>11.2f}  {row['note']}"
        )
    print()
    print("Reading:")
    print("  CB0/LoRA = CB0 supervised tokens per LoRA parameter. The ABSOLUTE")
    print("    value is regime-dependent (LoRA is heavily regularized, so low")
    print("    ratios are workable) -- read the CROSS-ARM TREND: each rank")
    print("    doubling halves it (r16->r32->r64 here), so the lowest-ratio arm")
    print("    is the one most at risk of outrunning its CB0 supervision.")
    print("    Sensitive to avg_frames -- MEASURE it (--pt-dir), don't trust the default.")
    print("  CB0 tok/p, allCB tok/p divide by ALL trainables (incl. depth path).")
    print(f"  CAVEAT: ~{DEAD_AUDIO_HEADS / 1e6:.0f}M of 'fixed' are audio_heads[1:8], which")
    print("    never reach the loss (composite uses head[0] only) -- dead capacity")
    print("    counted in the audit but not effectively trained. See module docstring.")
    print("  Exact trainable counts: see the training startup printout.")


if __name__ == "__main__":
    main()
