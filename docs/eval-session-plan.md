# v0.3 GPU eval session — pruned execution plan (Lambda, hub-first)

One-page checklist for the release-eval session. Full design:
[`v0.3-evals-plan.md`](v0.3-evals-plan.md); operating manual:
[`evals-runbook.md`](evals-runbook.md). **Everything pulls from the HF hub**
(public repo + dataset repos) — the box needs NO gcloud, only three tokens.

Box: **Lambda A100 40 GB** (sized 2026-07-22: peak ≈18 GB bf16; stages never
stack). Model source: `tiny-aya-translate/tr-hi-s2st-v0.3` —
`@best` = step 76,000 (val composite 2.8199), `@step-76250` = final.

## 0. Bringup (~10 min)

```bash
git clone https://github.com/tiny-aya-simultaneous-translation/model.git && cd model
uv sync --extra eval
export HF_TOKEN=...          # gated tiny-aya-base + hub pushes
export WANDB_API_KEY=...     # backfill into run xzcb60bl
export GEMINI_API_KEY=...    # referee + GEMBA judge   (env only, NEVER print)
```

## 1. Data staging (hub-only)

- Corpus val: `val.jsonl` split + encoded `.pt` dir from
  `tiny-aya-translate/tr-hi-mimi-encoded` (only val-referenced rows needed).
- FLEURS: `packed/encoded_pt.tar.gz` + `packed/encoded_alignments.tar.gz` +
  `splits/val.jsonl` from `tiny-aya-translate/fleurs-tr-hi-mimi-encoded`
  (~30 MB), extract.

## 2. Smoke (~10 min — MANDATORY before anything else)

```bash
uv run python scripts/eval_release.py \
  --checkpoint hub:tiny-aya-translate/tr-hi-s2st-v0.3@step-1000 \
  --subset eval/subsets/v03-val-500.jsonl \
  --val_jsonl <val.jsonl> --encoded_dir <encoded> \
  --device cuda --limit 8 --n_bootstrap 1 \
  --stages generate,asr,text,report --output_dir eval_out/smoke
```
Verifies: hub weights-only bundle loads (peft_adapter present), CUDA path,
both Whisper judges, wav dumps. Stages are RESUMABLE (per-stage jsonl).

## 3. Tier-2 full passes (GPU)

Run for `@best`, then `@step-76250` (~run in tmux; record wall-clock + $):

```bash
uv run python scripts/eval_release.py \
  --checkpoint hub:tiny-aya-translate/tr-hi-s2st-v0.3@best \
  --subset eval/subsets/v03-val-500.jsonl \
  --val_jsonl <val.jsonl> --encoded_dir <encoded> \
  --device cuda --gemini_referee 25 \
  --stages generate,asr,text,mos,latency,report \
  --output_dir eval_out/best-76000 \
  --wandb_run cataluna84/tinyaya-stage2-tpu/xzcb60bl \
  --hub_repo tiny-aya-translate/tr-hi-s2st-v0.3
```

**Sanity gates (abort/flag if violated):**
1. GT-audio topline ≫ model score (topline = judge on GT target audio);
2. judge floor consistent with corpus QC (86% pass @ WER ≤ 0.20);
3. DNSMOS(GT) ≈ codec ceiling (MOS reported as Δ(gen−GT) ONLY).

## 4. LAWA candidate

```bash
uv run python scripts/average_checkpoints.py \
  --repo tiny-aya-translate/tr-hi-s2st-v0.3 \
  --steps 66000..76000 --out /tmp/lawa   # late per-1000 window (hub weights)
# then eval /tmp/lawa exactly like a checkpoint (same Tier-2 command)
```

## 5. Tier-3 (separate venv — sonar/comet conflict with training pins)

```bash
uv venv ~/eval-sem && source ~/eval-sem/bin/activate
uv pip install torch sonar-space unbabel-comet sacrebleu soundfile
# accept the gated Unbabel/wmt22-cometkiwi-da license once
python scripts/eval_release.py ... --stages semantic,judge,report
```
On best / final / LAWA: BLASER-2.0 QE+Ref, CometKiwi + COMET-ref, GEMBA
adequacy (temp 0, self-agreement reported).

## 6. FLEURS acoustic-shift pass (winner only)

Same commands, `--subset eval/subsets/v03-fleurs-200.jsonl`, FLEURS
`--val_jsonl/--encoded_dir`, output `eval_out/<ckpt>-fleurs`.
⚠️ Label results ACOUSTIC shift only (200/200 text overlap, audited).

## 7. Pick the release checkpoint

`src/evaluation/text_metrics.paired_bootstrap` best-vs-LAWA-vs-final —
report p-values; chrF++ primary, BLEU secondary (unreliable < ~5).

## 8. Land the numbers

Each pass wrote `results.json` (judge ids, subset digest, NORM_VERSION,
decoding, seed, timings) + W&B backfill at the checkpoint's global_step +
hub `eval/` push. Next session: card `model-index` + Evaluation section +
reval report + blog — all from the same results.json.

## Reference

| item | value |
|---|---|
| judges | hi: `vasista22/whisper-hindi-large-v2` · tr: `openai/whisper-large-v3` |
| normalizer | `NORM_VERSION=hi-tr-v1` |
| subsets | `v03-val-500` sha `91c7e275…` · `v03-fleurs-200` sha `5105afa6…` |
| decoding | greedy (`--ar_temp 0`) for comparability |
| disclosures | refs are MT-synthetic; FLEURS = acoustic shift; MOS = Δ only |

Optional strengthenings (Exa-validated 2026-07-22, apply if time allows):
BLASER-2.0 deserves headline placement next to chrF++ (superior human
correlation for X→non-English; SeamlessM4T evidence); GEMBA judge benefits
from ~5–10 passes with outlier-robust averaging (GEMBA-MQM V2, WMT25).
