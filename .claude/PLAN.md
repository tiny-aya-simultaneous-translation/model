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

## In flight
- [ ] Fresh-provision drill verdict (HF-direct backbones+dataset on wiped hosts;
      digest must equal the GCS-tarball digest) + GCS restage to launch-ready
- [ ] Hub smoke (300 steps → throwaway private repo; verify branch/samples/logs)

## Next
- [ ] **Launch** (explicit user word): fresh QR via `launch_spot.sh` + metadata
      gates; qr_watch babysitter; watchdog cadence ~30 min
- [ ] During-run: watch dashboard; early stop ⇒ `_mh_anneal.yaml` runbook
- [ ] Post-run: LAWA average → eval (best/final/averaged; corrected AR loop) →
      `publish_checkpoint_suite.py` backfill → flip hub public → model card
      eval numbers + release notes

## Definition of Done
Public HF repo with the full revision suite + audio + logs, model card with eval
numbers (ASR-BLEU/chrF/DNSMOS), report + PR #10 closed out.
