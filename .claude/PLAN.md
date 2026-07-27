# PLAN — v0.3 TR↔HI S2ST public release (SHIPPED)

**PR #10 MERGED** 2026-07-26 (`5d0bc02` → `main`); **GitHub `v0.3` release
promoted** out of pre-release; **blog published**. Trail:
[`docs/v0.3-eval-report.md`](../docs/v0.3-eval-report.md) +
[`docs/v0.3-public-release-plan.md`](../docs/v0.3-public-release-plan.md).

## Goal
Ship v0.3 **text+audio** TR↔HI S2ST as a public, Pythia-style keep-all checkpoint
suite (110,463-step long-horizon config, trained to 76,250 on multi-host v6e-16),
with a full honest eval and a lean, secret-free public repo.

## Done — train + eval
- [x] Long-horizon run COMPLETE (W&B `xzcb60bl`): WSD plateau early-stop @65,250 +
      anneal 65,250→76,250 → **best val composite 2.8199 @ step 76,000**, 2.07
      epochs, zero preemptions.
- [x] Repo PUBLIC (`tiny-aya-translate/tr-hi-s2st-v0.3`) + full ~89-ckpt suite.
- [x] **Release eval DONE**: free-run text chrF++ **25.7 / 25.1**, ASR-chrF++
      **3.7 / 9.6** vs **92 / 87** GT-audio topline, BLASER-QE ~2.5, DNSMOS Δ−1.34,
      RTF 0.95; **@best ≈ @final, LAWA rejected**; FLEURS = acoustic-shift only.
- [x] W&B public + `eval/*` backfilled + **emergence report** created.
- [x] Framing: language-identity → **text translation emerges** → **audio
      synthesis is the frontier**.

## Done — release hygiene
- [x] De-bloat 276→202 tracked files; portable `fleurs-200`; foreign paths
      genericized; pre-flattening leftovers deleted from disk.
- [x] Gemini key scrubbed (never in git history) + **ROTATED**.
- [x] All 11 release-facing `.md` synced to final (evals, training, W&B report +
      blog links, status complete; recipe `exclude_top: 0`; URL typo fixed).
- [x] **License = CC-BY-NC-4.0** for weights (base `tiny-aya-base` verified
      `cc-by-nc-4.0`, so apache-2.0 would be invalid); Moshi/Mimi CC-BY-4.0;
      code Apache-2.0.
- [x] HF card re-uploaded (twice: eval/report/blog content, then `blob/main` links).

## Done — ship
- [x] **PR #10 merged → `main`** (`5d0bc02`); `main` = 202 tracked files.
- [x] **GitHub `v0.3` promoted**: `prerelease=false`, refreshed title + 5,072-char
      notes (eval table, artifact links, CC-BY-NC-4.0, TRC ack), no stale phrases.
      Tag stays at `e89fb26` (training-code freeze) — deliberately **not retagged**
      (retagging a published tag breaks anyone who already fetched it); the notes
      state the tag marks the freeze while `main` carries the final docs.
- [x] **Blog PR #14 MERGED** 2026-07-24 (`d1f07ac`) — published post verified live
      with the v0.3 content (author byline, TRC ack, emergence framing, W&B links).

## Done — post-release sweep (PRs #11–#14, all merged 2026-07-27)
- [x] **#11** card eval-report links `blob/feat/…` → `blob/main`.
- [x] **#13** `example.env` + credentials docs, and the **`.gitignore` hardening**
      that closed the `launch.env` leak path (`*.env` + `.env.*` + `*.env.*`,
      `!example.env`, `.envrc`, credential blobs).
- [x] **#14** repo-wide alignment: invalid `CITATION.cff` + `NOTICE` that claimed
      Apache-2.0 over the **CC-BY-NC-4.0 weights**; `pyproject` 0.1.0 → 0.3.0 with
      `[project.urls]`; `onboarding.md` rewritten (717→454, symbol-cited); ~20 dead
      references cleared; ruff 26 → **0** and enforced in CI; byte-compile widened
      5 → 87 files; community-health files; TPU cold-boot clone URL fixed.
- [x] **#12** `.claude` restructure (archive deleted, memory files tracked,
      `settings.local.json` still excluded) + **`_lib.relativize_paths()`** so hook
      entries stop leaking `/home/<user>/…` into a public repo. Pinned by
      `tests/test_hook_path_relativization.py`.
- [x] **HF card re-uploaded** and live-verified after the merge.
- [x] **Infrastructure torn down** — QR `tinyaya-v6e16-eu-qr` deleted; verified
      **zero queued resources and zero TPU VMs** across `europe-west4-a`,
      `us-east1-d`, `us-central2-b`. No compute cost accruing.

`main` @ `4e906da`, 216 tracked files; both CI gates green, ruff clean, 193 tests.

## Next (optional, nothing blocking)
- [ ] Dataset cards (alignments note).
- [ ] Make `data-pipeline` public if its README link should resolve for outside
      readers (currently private → 404 anonymously; the link itself is correct).
- [ ] Cut a fresh tag at `main` if the release should point at the final state
      rather than the `e89fb26` code freeze.
- [ ] GCS still holds the ~411 GB checkpoint suite — intentional (it backs the
      published Pythia-style suite), but it is the one ongoing cost.

## Definition of Done
✅ **Met.** Public HF repo + full checkpoint suite + card with eval numbers; eval
report, W&B run + emergence report, and blog all telling one consistent
CC-BY-NC-4.0 story; PR #10 merged; `v0.3` release promoted; blog published; the
post-release sweep merged; infrastructure torn down.

## Ops note (learned the hard way, 2026-07-27)
Branch-switching can **delete** the `.claude` memory files whenever they are
tracked on one branch and gitignored on the other — git removes the tracked copy,
and the ignore rule stops it coming back. That is exactly how `PLAN.md` was lost
once: `git checkout main` onto a *stale* local `main` (where they were still
tracked) + `git reset --hard origin/main`.

**This is live until PR #12 merges** — they are tracked on
`chore/track-claude-tooling` but ignored on `main`, so switching between those two
deletes them. Mitigations: `git fetch && git checkout -B main origin/main` (never
land on a stale `main`), or copy the files aside first. Recover a lost copy with
`git show 950b159^:<path> > <path>` (anything rewritten locally after the
untracking commit was never committed and is unrecoverable).
