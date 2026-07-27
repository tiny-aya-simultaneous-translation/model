# PLAN — v0.3 TR↔HI S2ST public release (SHIPPED)

**PR #10 MERGED** 2026-07-26 (`5d0bc02` → `main`); **GitHub `v0.3` release
promoted** out of pre-release. Trail:
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
- [x] De-bloat 276→202 tracked files; `.claude/` archive + session state untracked
      (local only); portable `fleurs-200`; foreign paths genericized.
- [x] Gemini key scrubbed (never in git history) + **ROTATED**.
- [x] All 11 release-facing `.md` synced to final (evals, training, W&B report +
      blog links, status complete; recipe `exclude_top: 0`; URL typo fixed).
- [x] **License = CC-BY-NC-4.0** for weights (base `tiny-aya-base` verified
      `cc-by-nc-4.0`, so apache-2.0 would be invalid); Moshi/Mimi CC-BY-4.0;
      code Apache-2.0.
- [x] HF card re-uploaded (twice: eval/report/blog content, then `blob/main` links).

## Done — ship
- [x] **PR #10 merged → `main`** (`5d0bc02`); `main` = 202 tracked files.
- [x] Card eval-report links repointed `blob/feat/…` → `blob/main` — **PR #11**
      (CI green, open); HF live card verified 0 × `blob/feat`.
- [x] **GitHub `v0.3` promoted**: `prerelease=false`, refreshed title + 5,072-char
      notes (eval table, artifact links, CC-BY-NC-4.0, TRC ack), no stale phrases.
      Tag stays at `e89fb26` (training-code freeze) — deliberately **not retagged**
      (retagging a published tag breaks anyone who already fetched it); the notes
      state the tag marks the freeze while `main` carries the final docs.

## Next
- [ ] Merge **PR #11** (2-line link fix, CI green).
- [ ] Merge blog PR **Cohere-Labs-Community/blog#14** (publishes the updated post).
- [ ] Optional: dataset cards (alignments note); make `data-pipeline` public if its
      README link should resolve externally; delete the SUSPENDED QR
      `tinyaya-v6e16-eu-qr` (cleanup only — slice already preempted).
- [ ] Optional: cut a fresh tag at `main` if the release should point at the final
      state rather than the code freeze.

## Definition of Done
✅ Public HF repo + full checkpoint suite + card with eval numbers; eval report,
W&B run + emergence report, and blog all telling one consistent CC-BY-NC-4.0
story; PR #10 merged; `v0.3` release promoted. Remaining: merge PR #11 + blog #14.

## Ops note (learned the hard way, 2026-07-27)
`.claude/{PLAN,PROGRESS,VERIFY,memories}.md` + `archive/` are **gitignored, local
only**. A `git checkout main` onto a *stale* local `main` (where they were still
tracked) followed by `git reset --hard origin/main` **deletes them from disk**.
Recover with `git show 950b159^:<path> > <path>`. Before switching branches, either
`git fetch && git checkout -B main origin/main`, or back these files up first.
