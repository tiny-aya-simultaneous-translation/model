# PLAN — v0.3 long-horizon run → eval → public release

Branch: `feat/v0.3-implementation` (PR #10). Full trail:
[`docs/v0.3-reval-report.md`](../docs/v0.3-reval-report.md) (addenda A.1–A.5) +
[`docs/v0.3-public-release-plan.md`](../docs/v0.3-public-release-plan.md).

## Goal
Ship v0.3 **text+audio** TR↔HI S2ST as a public, Pythia-style keep-all checkpoint
suite trained by the 110,463-step long-horizon run on multi-host v6e-16.

## Done (validated live)
- [x] Multi-host DP pipeline (real global batch 32; gradient-identity proven)
- [x] Phase-E spokes ×4 + pre-launch hardening (staging identity, preflight gates,
      cross-host digest, HF offline, qr_watch, manifest, val×4) — all drilled
- [x] Probe verdicts: flash-attn OFF, compile-cache DOA, grad-ckpt ON, chunk 100,
      b4/chip = OOM envelope
- [x] Public-release instrumentation (tokens axes, ppl, codebook entropy/active,
      MFU, ckpt index, per-host 16-chip telemetry, provenance) + inline TPU audio
      demos + offline eval proxy — verified on the 2k/5k dress rehearsals
- [x] HF-direct primary / WARP fallback (route fixed upstream 2026-07-15)
- [x] Async HF-hub publishing (private `tiny-aya-translate/tr-hi-s2st-v0.3`)
- [x] Repo-wide docs sync + `check_docs_sync.sh` CI guard
- [x] Fresh-provision drill PASS (HF-direct backbones+dataset, byte-identical
      digest on all 4 hosts) + GCS restage to launch-ready
- [x] Hub smoke PASS (300 steps → throwaway repo; branches/samples/logs verified)
- [x] **Evals program** (docs/v0.3-evals-plan.md): `src/evaluation/` package,
      `eval_release.py` (8 resumable stages), Tier-1 proxy gold-ref upgrade,
      frozen subsets `v03-val-500` + `v03-fleurs-200` (FLEURS = acoustic shift
      only; 200/200 text overlap audited), runbook — GPU live-verify SHELVED
      to post-run (docs/do.md)

## Next
- [x] Attempt-2 restart executed 2026-07-17 (run xzcb60bl, code 6dcc9e1) —
      **COMPLETED by designed early stop 2026-07-19 at step 65,250**
      (patience 10; best val/composite 2.9048 @ step 62,750; exit 0;
      canonical final save `step_065250_final`; GCS keep-all suite complete:
      78 checkpoint dirs)
- [x] Hub interim suite DONE 2026-07-19/20: 12/12 branches weights=YES
      (per-6000 + best@62,750 + final 65,250, 45.4 GB) + `main:checkpoints/`
      mirror for file-tree discoverability (Xet dedup verified ~storage-free);
      model card refreshed (run results, playable samples, checkpoints table,
      CC-BY-NC-4.0 license correction, blog link); governance files
      (CONTRIBUTING.md, CITATION.cff); published log cleaned 7,851→927 lines
- [x] **Anneal leg DONE 2026-07-20** (user go): 65,250 → 76,250, linear
      LR→0; best val composite **2.8199 @ 76,000** (vs plateau 2.9048);
      zero preemptions; plan docs/v0.3-anneal-leg-plan.md + PR #10
- [x] Repo PUBLIC + full ~89-checkpoint suite DONE 2026-07-20 (branches +
      main:checkpoints/, ~340 GB via publish_suite_rate_aware.py); card
      pushed with anneal results (2.8199); GCS pruned (attempt-1 + xla-cache
      deleted, r2 411 GB suite kept, complaints bucket removed)
- [ ] **DECISION: delete the SUSPENDED QR** (slice preempted post-run — QR
      tinyaya-v6e16-eu-qr SUSPENDED, node gone; all work finished. Teardown =
      `gcloud compute tpus queued-resources delete tinyaya-v6e16-eu-qr
      --zone=europe-west4-a` on user word)
- [ ] Tier-1 eval proxy sweeps on saved checkpoints (CPU, actionable NOW —
      docs/evals-runbook.md "Post-run state")
- [ ] GPU eval session (UNBLOCKED — do.md; rent on user word):
      eval_release.py full pass → LAWA average → paired-bootstrap
      best-vs-LAWA-vs-final
- [ ] Blog revision (USER-OWNED, do.md): training run / curriculum / infra
      tables / checkpoint story; evals numbers after the GPU session
- [ ] Remaining for full release: model-index eval numbers (GPU session on
      annealed best 76,000/final/LAWA), W&B project visibility,
      release notes / GitHub v0.3 release promotion

## Definition of Done
Public HF repo with the full revision suite + audio + logs, model card with eval
numbers (ASR-BLEU/chrF/DNSMOS), report + PR #10 closed out.
