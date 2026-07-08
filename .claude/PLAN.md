# PLAN — v0.3 text+audio reval → production run → eval → public release

Branch: `feat/v0.3-implementation` (PR #10). Strategy detail:
[`docs/v0.3-reval-sweep-plan.md`](../docs/v0.3-reval-sweep-plan.md) (amended 2026-07-08) +
[`docs/v0.3-public-release-plan.md`](../docs/v0.3-public-release-plan.md).

## Goal
Ship the v0.3 **text+audio** TR↔HI S2ST translator: re-validate the recipe with the 6-arm
text+audio sweep on v6e-8s, run the winner to completion on v6e-16, evaluate honestly, and
publish everything (model, all checkpoints, dataset cards, code, blog — including the
audio-only-misdiagnosis story).

## Definition of Done
- [ ] 6 reval arms (A–F, text_weight 0.2, group `v03-5k-reval-ta`) reach 5,000 steps;
      winner picked per the amended selection rule (text gate + post-hoc composite sweep).
- [ ] v0.3 production run completes (14,532 steps / 3 epochs, text+audio + scan recipe)
      on v6e-16 with the winner's knobs; `best_by_val` chosen.
- [ ] Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
      `val/text_acc`, ASR-BLEU, DNSMOS — filled into the v0.3 card.
- [ ] v0.3 HF repo published (card + all checkpoints); dataset card documents the
      alignment layout (root-level `{stem}.{src,tgt}.alignments.json`) + the ~5% missing-pt gap.
- [ ] Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- [ ] Blog updated to the text+audio result + the honest misdiagnosis arc; leaked tokens
      rotated before public.

## State (2026-07-08)
- **v6e-8 scan enablement DONE** (9 blockers root-caused; commits `812a0df..77d0cf2`;
  PR #10 comments) — 8.4 s/step, peak 25–29 G at batch 4×8; recipe mandatory, see
  `docs/tpu-runbook.md`. ✅
- **TEXT+AUDIO PIVOT** (user decision): corpus DOES ship alignments (840,426×2, 100%);
  loader fixed (`_resolve_alignment` + fail-loud guard, proven live 100% coverage);
  `val/text_acc` added; configs flipped (arms + production); docs + memory reconciled. ✅
- **Audio-only arms stopped** at ~step 100–125 (partials in group `v03-5k-reval`). ✅
- **TA gate smoke** on arm-a: RUNNING (text CE < 11.5 falling = gate). ⏳
- **scan3 full-corpus dataprep**: RUNNING (extracting; then arm D + Phase-0c tarball —
  tarball MUST include the root-level alignment JSONs). ⏳
- **Arms E/F**: need fresh QRs; quota requires deleting `smoke-b1` (user approval). ☐
- **Uncommitted**: loader fix + test, text_acc metric, config flips, docs. ☐

## Next steps
1. Smoke gate passes → hot_redeploy arms A/B/C (nodes keep staged data).
2. scan3 dataprep done → build Phase-0c tarball (encoded + splits + alignments) → arm D.
3. Delete `smoke-b1` (user) → launch E/F from the tarball.
4. Commit series + PR #10 pivot comment with smoke evidence.
5. Arms finish (~11–12 h) → selection rule → update production config → launch v6e-16.
6. Eval at `best_by_val` → publish per release plan; rotate secrets; flip repos public.

## Guardrails
- TPU slices are a free TRC grant — never stop/delete/reprovision without explicit intent.
- Keep the GCS bucket in the TPUs' region (europe-west4) — a cross-region bucket re-incurs
  the egress that was ~98% of the bill.
- No persistent XLA compile cache → minimize restarts (~35–40 min recompile each; scan
  cuts it substantially).
- SUSPENDED/FAILED QR husks hold quota — delete promptly (with approval).
- New experiment ⇒ new `save_dir` (`--resume auto` will happily resume the old run).
