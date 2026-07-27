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

`main` @ `0d9460f`, 216 tracked files; both CI gates green, ruff clean, 193 tests.

## Done — HuggingFace org brought to release standard (2026-07-27)

Admin access landed, so the whole org was audited and fixed: **26 repos → 20
public (7 models + 13 datasets) + 6 private, 0 missing metadata, 85/85 card URLs
resolving.**

- [x] **LEGAL — `tr-hi-s2st-v0.1`, `v0.2` and the private `…-tr-hi-pt` were
      published as `apache-2.0`.** All three are LoRA derivatives of
      `CohereLabs/tiny-aya-base` (`cc-by-nc-4.0`), so the non-commercial term is
      inherited and Apache was never ours to grant. Corrected on the Hub **and**
      in the repo sources (`docs/hf-model-card-tr-hi-s2st-v0.{1,2}.md` still said
      Apache too, so it would have regressed on the next upload).
- [x] **Dataset licences.** Every dataset previously declared *none*.
      FLORES-derived corpora → `cc-by-sa-4.0` (share-alike propagates); eval sets
      → `other` + upstream note, rather than inventing a licence.
- [x] **The `tr-hi-mimi-encoded` P0.** Its card documented `.pt` keys as
      `source_text`/`target_text` (real: `src_text`/`tgt_text`) and alignment
      paths as `encoded/<stem>_src.json` (real: `{stem}.src.alignments.json` at
      the data root) — the very mismatch that made v0.1/v0.2 train audio-only.
      Corrected, with the resolution order spelled out.
- [x] **13 new cards**, incl. `fleurs-tr-hi-parallel-speech` (11,383 files,
      previously undocumented) and the 2 stray trainer `push_to_hub` artifacts,
      now labelled superseded → v0.3.
- [x] **GitHub ↔ HF cross-links on every card.** Verified mapping, not guessed:
      `codec-finetuning` is what the whole phase-3 cluster exists for, and
      `hindi-tts-probe` benchmarks directly on `lahaja-eval` — the study that
      chose the Hindi ASR judge used in the v0.3 eval. The three **private**
      GitHub repos are deliberately never linked as browsable.
- [x] **Shared lineage footer** everywhere: `parallel-text → parallel-speech →
      mimi-encoded → v0.3`, plus eval report, W&B run + emergence report, blog,
      TRC acknowledgement, and the honest framing (text translates ~25 chrF++;
      intelligible audio synthesis is the frontier).
- [x] **Housekeeping.** 4 empty models + 1 empty dataset → private (reversible,
      nothing deleted); `turkish-{cv,openslr}-24k-phase3` stay public with
      placeholder cards.

Tooling: `~/Workspace/v0.3-work/hf_release_cards.py` — idempotent and
re-runnable, preserving every auto-generated `dataset_info` block.

## Next (other, optional)
- [ ] Make `data-pipeline` public if its README link should resolve for outside
      readers (currently private → 404 anonymously; the link itself is correct).
- [ ] Cut a fresh tag at `main` if the release should point at the final state
      rather than the `e89fb26` code freeze.
- [x] ~~GCS checkpoint suite cost~~ — bucket deleted 2026-07-27; zero cloud cost.
      Note the trade: it held the only optimizer state, so the published
      checkpoints support inference/eval/averaging but **not** resume.

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
