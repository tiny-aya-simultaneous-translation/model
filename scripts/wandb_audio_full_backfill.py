"""Backfill the curriculum-independent audio loss into a W&B training run.

WHY THIS EXISTS
---------------
`train/audio_loss` is the CURRICULUM loss: under progressive coarse->fine
unmasking (loss.progressive_unmask_fraction / unmask_k0, see
src/training/codebook_schedule.py) its definition GROWS at every unmask onset
(one more codebook's CE joins the weighted mean), so the public chart shows a
sawtooth: +0.3..0.6 jumps at steps ``(c - k0) * unmask_steps / (K - k0)`` that
are pure metric accounting, not regressions (verified live on run 1021mlne:
each codebook's own CE is flat through its onset).

The fix does not require touching a run: ``train/per_codebook_loss_{i}`` is
logged every log step from the PRE-mask per-codebook CE tensor
(src/training/translation_loss.py), so the smooth all-codebook series is
derivable for the run's ENTIRE history. This script derives it and (optionally)
logs it back into the same run keyed on ``global_step`` -- the project's
standard backfill pattern (eval_translation_proxy.py) -- as:

* ``train/audio_loss_full``          -- unweighted mean CE over all K codebooks
* ``train/audio_loss_full_weighted`` -- multiplier-weighted mean (no unmasking)

New runs log ``train/audio_loss_full`` natively (train_hierarchical.py); this
script exists for runs recorded before that metric landed.

SAFETY: ``--backfill`` REFUSES while the run is still running -- a second
concurrent writer to a live multi-host shared-mode run is never safe. Derive
with ``--print``/``--csv`` any time; backfill after the run finishes.

Usage:
    python scripts/wandb_audio_full_backfill.py \
        --run cataluna84/tinyaya-stage2-tpu/1021mlne --print
    python scripts/wandb_audio_full_backfill.py \
        --run cataluna84/tinyaya-stage2-tpu/1021mlne --csv /tmp/audio_full.csv
    python scripts/wandb_audio_full_backfill.py \
        --run cataluna84/tinyaya-stage2-tpu/1021mlne --backfill   # finished runs only
"""

from __future__ import annotations

import argparse


def derive_full_series(
    rows: list[dict],
    num_codebooks: int,
    multipliers: list[float] | None = None,
) -> list[tuple[int, float, float]]:
    """Return [(global_step, mean_all_cb, weighted_mean_all_cb)] sorted by step.

    ``rows`` are W&B history rows carrying ``global_step`` and
    ``train/per_codebook_loss_{i}`` for all ``i`` in range(num_codebooks); rows
    missing any codebook key are skipped (e.g. rows from other log families).
    The weighted variant applies ``multipliers`` WITHOUT the unmask schedule --
    same weighting as the converged (post-curriculum) train/audio_loss, so the
    two series coincide once unmasking completes.
    """
    if multipliers is None:
        multipliers = [1.0] * num_codebooks
    if len(multipliers) != num_codebooks:
        raise ValueError(
            f"multipliers has {len(multipliers)} entries, expected {num_codebooks}"
        )
    wsum = sum(multipliers)
    keys = [f"train/per_codebook_loss_{i}" for i in range(num_codebooks)]
    out: list[tuple[int, float, float]] = []
    for r in rows:
        gs = r.get("global_step")
        if gs is None:
            continue
        vals = [r.get(k) for k in keys]
        if any(v is None for v in vals):
            continue
        mean = sum(vals) / num_codebooks
        wmean = sum(m * v for m, v in zip(multipliers, vals, strict=True)) / wsum
        out.append((int(gs), float(mean), float(wmean)))
    out.sort(key=lambda t: t[0])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="entity/project/run_id")
    ap.add_argument("--num_codebooks", type=int, default=8)
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--csv", default=None, help="write series to this CSV path")
    ap.add_argument(
        "--backfill",
        action="store_true",
        help="log the series back into the run (REFUSED while run is running)",
    )
    args = ap.parse_args()

    import wandb  # lazy: derivation math above stays importable without wandb

    api = wandb.Api(timeout=60)
    run = api.run(args.run)

    mult = None
    loss_cfg = run.config.get("loss") if isinstance(run.config, dict) else None
    if isinstance(loss_cfg, dict):
        mult = loss_cfg.get("per_codebook_multipliers")
    keys = ["global_step"] + [
        f"train/per_codebook_loss_{i}" for i in range(args.num_codebooks)
    ]
    rows = list(run.scan_history(keys=keys, page_size=2000))
    series = derive_full_series(rows, args.num_codebooks, mult)
    print(
        f"[audio-full] run={args.run} state={run.state} rows={len(series)} "
        f"multipliers={mult or 'uniform'}"
    )
    if not series:
        raise SystemExit("[audio-full] REFUSING: no per-codebook history found")

    if args.do_print:
        for gs, m, wm in series:
            print(f"{gs}\t{m:.4f}\t{wm:.4f}")
    if args.csv:
        with open(args.csv, "w") as f:
            f.write("global_step,audio_loss_full,audio_loss_full_weighted\n")
            for gs, m, wm in series:
                f.write(f"{gs},{m:.6f},{wm:.6f}\n")
        print(f"[audio-full] wrote {args.csv}")

    if args.backfill:
        if run.state == "running":
            raise SystemExit(
                "[audio-full] REFUSING --backfill: run is still running "
                "(no second writer on a live shared-mode run). Use --csv now; "
                "backfill after the run finishes."
            )
        entity, project, run_id = args.run.split("/")
        bf = wandb.init(
            entity=entity, project=project, id=run_id, resume="must"
        )
        # Same charts contract as the trainer: train/* plotted vs global_step.
        bf.define_metric("global_step", hidden=True)
        bf.define_metric("train/*", step_metric="global_step")
        for gs, m, wm in series:
            bf.log(
                {
                    "global_step": gs,
                    "train/audio_loss_full": m,
                    "train/audio_loss_full_weighted": wm,
                }
            )
        bf.finish()
        print(f"[audio-full] backfilled {len(series)} points into {args.run}")


if __name__ == "__main__":
    main()
