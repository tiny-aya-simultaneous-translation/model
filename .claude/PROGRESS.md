# PROGRESS

Append-only running log of changes, decisions, failures, and next steps.

Auto-managed by `.claude/hooks/post_tool_use.py`,
`.claude/hooks/stop.py`, `.claude/hooks/pre_compact.py`, and
`.claude/hooks/session_end.py`. Quick-capture entries land here when
you start a message with `#progress`. Manual capture via
`/progress <text>`.

Format per entry:

```
## YYYY-MM-DDTHH:MM:SSZ | <branch>@<short-sha> | <status> | <kind>
<one-line summary>

<optional detail block>
```

Status: `info | done | fail | block`

## 2026-07-20T23:30:00Z | feat/v0.3-implementation@5d78d1a | done | release
Anneal leg complete + repo PUBLIC + full suite + prune + preemption

- WSD anneal leg ran 65,250 → 76,250 (linear LR→0 from the plateau early-stop);
  **best val composite 2.8199 @ step 76,000** (vs 2.9048 plateau; ppl 1.489,
  text acc 96.6%). Resumed weights+Adam+RNG; same W&B run xzcb60bl.
- Repo `tr-hi-s2st-v0.3` flipped PUBLIC (50 GB private cap escaped); full
  ~89-checkpoint suite published (branches + `main:checkpoints/`, ~340 GB) via
  the rate-aware resumable publisher; model card updated + pushed (2.8199).
- Durable VM-side watcher (`scripts/tpu/vm_watcher.sh`) + W&B "crashed"-badge
  gotcha documented (heartbeat gaps on resumed shared-mode runs).
- Slice PREEMPTED post-run (QR SUSPENDED, all work done). GCS pruned:
  attempt-1 + xla-cache deleted, r2 411 GB suite kept, empty complaints bucket
  removed. NEXT: delete QR; GPU eval session (annealed best/final + LAWA);
  eval numbers → card; W&B public; GitHub release promote.

## 2026-07-20T05:30:00Z | feat/v0.3-implementation@241a52c | done | release
Long-horizon run COMPLETE + hub/card/docs release wave

- Run xzcb60bl finished 2026-07-19: designed early stop @ 65,250/110,463,
  best val composite 2.9048 @ 62,750, zero preemptions; GCS keep-all suite
  complete (78 dirs incl best_by_val + step_065250_final).
- Hub restructured under the ~50 GB private cap: 12-bundle interim ladder
  (branches) + main:checkpoints/ mirror (Xet dedup); published log cleaned
  7,851->927 lines; storage-limit circuit breaker + log-noise fixes landed.
- Model card fully refreshed (run results, playable audio, checkpoints
  table, CC-BY-NC-4.0 license correction, TRC, blog link) + CONTRIBUTING.md
  + CITATION.cff; GitHub pre-release tag v0.3 at e89fb26.
- NEXT: anneal-leg + slice-teardown decisions (user word); Tier-1 CPU
  sweeps; GPU eval_release.py session (UNBLOCKED); blog revision
  (user-owned, do.md); release flip w/ full 78 backfill.

## 2026-07-14T18:18:40Z | feat/v0.3-implementation@9b4709d | done | hardening
Pre-launch hardening pass COMPLETE — long-horizon run launch-ready on explicit user word.

Two silent failure modes found live + closed + drilled: contentless .unpacked
staging marker (would have trained 110k steps on the 4k subset) and the
zero-text alignment fallback (preflight gates expected-train-rows /
min-text-coverage + cross-host digest refusal). Probes on the idle v6e-16:
cadence/manifest/atomic-gate PASS in-bucket; flash-attn no-op (OFF);
grad-ckpt-off + chunk300 step-neutral (keep defaults); b4/chip OOM =
envelope; persistent XLA cache DOA (nondeterministic keys — stays off);
val×4 adopted (same 3200-sample gate, val cycle 210→120 s). Step budget:
1.8 s/step ≈ pure compute, infeed 0%, DCN ≤3%. Full corpus staged on all 4
hosts, byte-identical digests, coverage 100%. New: qr_watch.sh, anneal
template, stage_dataset.sh. Report addendum A.1–A.5; W&B group
v03-mh-hardening.

Kind: `edit | exec | decide | plan | verify | session`

The most recent entry is at the top. Older entries beyond 90 days are
moved to `.claude/archive/PROGRESS-YYYY-Qn.md` by the
`archive-progress` skill.

> **Full history through 2026-07-06 (13,998 lines) archived to
> [`.claude/archive/PROGRESS-2026-07-06.md`](archive/PROGRESS-2026-07-06.md).**
> The summary below is the current state; new entries append under it.

---

## 2026-07-27T04:41:51Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:41:10Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd /tmp && rm -rf /tmp/hooktest && mkdir -p /tmp/hooktest/home/Workspace/repo/.claude


## 2026-07-27T04:40:48Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:40:19Z | chore/track-claude-tooling@5e4fcc4 | done | edit
created `tests/test_hook_path_relativization.py`


## 2026-07-27T04:39:53Z | chore/track-claude-tooling@5e4fcc4 | done | edit
edited `.claude/hooks/_lib.py`


## 2026-07-27T04:39:49Z | chore/track-claude-tooling@5e4fcc4 | done | edit
edited `~/Workspace/tinyaya-stage2-scale/.claude/hooks/_lib.py`


## 2026-07-27T04:39:45Z | chore/track-claude-tooling@5e4fcc4 | done | edit
edited `~/Workspace/tinyaya-stage2-scale/.claude/hooks/_lib.py`


## 2026-07-27T04:39:12Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:38:13Z | chore/track-claude-tooling@5e4fcc4 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-27T04:37:55Z | chore/track-claude-tooling@5e4fcc4 | done | edit
edited `~/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-release-debloat.md`


## 2026-07-27T04:37:36Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:34:23Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:33:08Z | chore/track-claude-tooling@5e4fcc4 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:32:34Z | chore/track-claude-tooling@5d0bc02 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:32:19Z | chore/track-claude-tooling@5d0bc02 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:31:55Z | chore/track-claude-tooling@5d0bc02 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:31:42Z | chore/track-claude-tooling@5d0bc02 | done | edit
edited `~/Workspace/tinyaya-stage2-scale/.gitignore`


## 2026-07-27T04:31:08Z | chore/track-claude-tooling@5d0bc02 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:30:37Z | docs/repoint-links-to-main@82d4290 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:30:28Z | docs/repoint-links-to-main@82d4290 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-27T04:24:55Z | docs/repoint-links-to-main@82d4290 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-27T04:24:35Z | docs/repoint-links-to-main@82d4290 | done | edit
edited `~/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/MEMORY.md`


## 2026-07-27T04:24:33Z | docs/repoint-links-to-main@82d4290 | done | edit
created `~/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/claude-local-files-branch-switch-hazard.md`


## 2026-07-27T04:24:14Z | docs/repoint-links-to-main@82d4290 | done | edit
created `~/Workspace/tinyaya-stage2-scale/.claude/PLAN.md`


## 2026-07-27T04:23:17Z | docs/repoint-links-to-main@82d4290 | done | exec
cd ~/Workspace/tinyaya-stage2-scale


## 2026-07-22T21:39:00Z | feat/v0.3-implementation@245e7dc | done | exec
cd ~/Workspace/tinyaya-stage2-scale



## 2026-07-10T16:12:00Z | feat/v0.3-implementation@7de41ca | done | decide
DEAD-KEY DISCLOSURE: train.clip_grad_norm was never read (code reads max_grad_norm, default 1.0) — probes P1/P3 ran at clip 1.0, so clip 10 is UNTESTED (not rejected). P1 ⇒ pure cosine-schedule ablation, bounds run noise ≈0.6%; P3 ⇒ genuine batch-512@clip-1 rejection (+1.1%, cb0 −6pt). Verdict unchanged: production clip 1.0 @ 256 (pre-registered keep-validated rule). Fixed via load_config normalization (31894fc) + per-group diag/* telemetry (weight/grad RMS, lr×grad + Adam update sizes, clip_coef) enabled for production/smoke (9b1fa89); scripts/analysis/checkpoint_group_rms.py for finished runs (27e9f81); report/PR comment corrected (7de41ca). No sweep arm affected (all intended clip 1.0 = default).


## 2026-07-08T11:05:00Z | feat/v0.3-implementation@77d0cf2 | done | decide
TEXT+AUDIO PIVOT (user decision): "no text alignments" premise was FALSE — corpus ships 840,426×2 alignment JSONs (100% coverage) at the data root; the old check used legacy filenames and the loader only looked in encoded/.

Detail: audio-only arms stopped (~step 100-125); loader fixed (`dataset.py::_resolve_alignment`
+ fail-loud coverage guard, proven live: "alignment coverage 100.0%"); `val/text_acc` metric
added; configs flipped to text_weight 0.2 / composite 0.4/0.6 (reval base + all 6 arms +
production, which also got the scan recipe); namespace v03-5k-reval-ta /
stage2-reval-5k-ta/. Selection rule amended: text gate (CE<11.5 by 1k) + post-hoc
composite-weight sweep {0.2/0.8, 0.4/0.6, 0.5/0.5} from logged val series. Docs reconciled
(release plan premise correction, model card text+audio, runbook scan recipe + QR-husk-quota
+ pipefail gotchas, capacity log, do.md follow-ups incl. tarball MUST include alignment
JSONs). Earlier same day: 9-blocker v6e-8 scan enablement committed (812a0df..77d0cf2) +
PR #10 comments. In flight: TA gate smoke on arm-a; scan3 full-corpus dataprep (pipefail
bug fixed). Next: smoke gate → relaunch A/B/C → arm D → tarball → E/F → commit + PR comment.


## 2026-07-23T00:00:00Z | feat/v0.3-implementation | info | session
PROGRESS pruned for the public release: ~2,650 hook-auto-logged entries
(exec/edit/verify/session, 2026-07-06 to 07-22) removed to keep the log
lean; the curated summaries (release x2, hardening, decide x2) are kept
above. The full prior log remains in git history.
