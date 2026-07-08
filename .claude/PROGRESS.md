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
Kind: `edit | exec | decide | plan | verify | session`

The most recent entry is at the top. Older entries beyond 90 days are
moved to `.claude/archive/PROGRESS-YYYY-Qn.md` by the
`archive-progress` skill.

> **Full history through 2026-07-06 (13,998 lines) archived to
> [`.claude/archive/PROGRESS-2026-07-06.md`](archive/PROGRESS-2026-07-06.md).**
> The summary below is the current state; new entries append under it.

---

## 2026-07-08T09:25:07Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T09:22:48Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T09:20:37Z | feat/v0.3-implementation@ab196fe | done | edit
created `/home/cataluna84/.claude/jobs/2908a7e9/tmp/dataprep_scan3.sh`


## 2026-07-08T08:54:29Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:51:52Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 175,205p scripts/tpu/startup_script.sh


## 2026-07-08T08:51:43Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 135,175p scripts/tpu/startup_script.sh


## 2026-07-08T08:42:23Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:37:43Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:37:19Z | feat/v0.3-implementation@ab196fe | done | exec
gh pr comment 10 --body "**Clean-node validation confirmed** (follow-up to the blocker-chain comment above): \`tinyaya-smoke-scan3\` — fresh v6e-8 spot QR, dependencies from the lockfile only (no hand-installed packages) — is training with the full arm recipe:


## 2026-07-08T08:36:42Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-08T08:35:43Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:35:12Z | feat/v0.3-implementation@ab196fe | done | exec
gh pr comment 10 --body-file /home/cataluna84/.claude/jobs/2908a7e9/tmp/pr10-scan-fix-comment.md 2>&1


## 2026-07-08T08:34:38Z | feat/v0.3-implementation@ab196fe | done | edit
created `/home/cataluna84/.claude/jobs/2908a7e9/tmp/pr10-scan-fix-comment.md`


## 2026-07-08T08:32:50Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 1975,1995p scripts/train_hierarchical.py


## 2026-07-08T08:30:50Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:21:53Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:21:38Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan3_p2.sh


## 2026-07-08T08:21:31Z | feat/v0.3-implementation@ab196fe | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan3_p2.sh`


## 2026-07-08T08:19:44Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/pyproject.toml`


## 2026-07-08T08:19:05Z | feat/v0.3-implementation@ab196fe | done | exec
timeout 120 gcloud compute tpus tpu-vm ssh tinyaya-smoke-scan3 --project=ml-pipelines-315702 --zone=europe-west4-a --worker=0 --command='sudo /opt/tinyaya/.venv/bin/python -c "


## 2026-07-08T08:17:02Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:16:31Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-08T08:16:26Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 1580,1592p scripts/train_hierarchical.py


## 2026-07-08T08:16:21Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-08T08:14:32Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:13:47Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 2360,2385p scripts/train_hierarchical.py


## 2026-07-08T08:06:02Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T08:05:39Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan3.sh


## 2026-07-08T08:05:30Z | feat/v0.3-implementation@ab196fe | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan3.sh`


## 2026-07-08T07:58:42Z | feat/v0.3-implementation@ab196fe | done | exec
.venv/bin/ruff check src/model/lora_setup.py && .venv/bin/python -c "


## 2026-07-08T07:58:33Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T07:58:28Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T07:58:22Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T07:48:03Z | feat/v0.3-implementation@ab196fe | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name.basename(),state.state)" 2>&1


## 2026-07-08T07:26:53Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-08T04:25:59Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-08T04:17:05Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/backend/tpu_backend.py`


## 2026-07-08T04:14:22Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T04:08:46Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 10,30p /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/17d314e3-e3cf-4aa6-9405-42a5291ed074/tasks/b3vpwuh6c.output


## 2026-07-08T04:06:33Z | feat/v0.3-implementation@ab196fe | done | exec
python3 - <<'EOF'


## 2026-07-08T04:05:04Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/stage2_tpu_v6e8_reval.yaml`


## 2026-07-08T04:03:59Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/do.md`


## 2026-07-08T04:03:48Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-public-release-plan.md`


## 2026-07-08T04:03:31Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/hf-model-card-tr-hi-s2st-v0.3.md`


## 2026-07-08T03:56:19Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T03:50:46Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T03:50:23Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-08T03:50:06Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v3.sh


## 2026-07-08T03:48:55Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/reval/smoke_scan.yaml`


## 2026-07-08T03:48:46Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-08T03:48:28Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-08T03:42:32Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T03:41:25Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 20,70p scripts/tpu/launch_reval_arms.sh; sed -n 100,145p scripts/tpu/launch_reval_arms.sh


## 2026-07-08T03:40:09Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-08T03:39:32Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T03:39:16Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T03:39:08Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T03:38:54Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py`


## 2026-07-08T03:38:08Z | feat/v0.3-implementation@ab196fe | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name.basename(),state.state)" 2>&1


## 2026-07-08T03:34:02Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T03:33:27Z | feat/v0.3-implementation@ab196fe | done | exec
.venv/bin/ruff check src/model/depth_decoder.py && .venv/bin/python -c "


## 2026-07-08T03:32:54Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/depth_decoder.py`


## 2026-07-08T03:14:48Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T03:14:35Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-08T03:14:22Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v3.sh


## 2026-07-08T03:13:30Z | feat/v0.3-implementation@ab196fe | done | exec
.venv/bin/ruff check src/model/depth_decoder.py && .venv/bin/python -c "


## 2026-07-08T03:12:50Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/depth_decoder.py`


## 2026-07-08T03:12:44Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/depth_decoder.py`


## 2026-07-08T02:47:42Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T02:47:28Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v3.sh


## 2026-07-08T02:46:09Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/pyproject.toml`


## 2026-07-08T02:45:43Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 1080,1140p /home/cataluna84/Workspace/tinyaya-stage2-scale/.venv/lib/python3.12/site-packages/torch_xla/core/xla_builder.py


## 2026-07-08T02:41:45Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T02:41:29Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-08T02:41:15Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v3.sh


## 2026-07-08T02:41:03Z | feat/v0.3-implementation@ab196fe | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v3.sh`


## 2026-07-08T02:39:54Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/pyproject.toml`


## 2026-07-08T02:39:03Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 80,140p scripts/tpu/_remote_redeploy.sh


## 2026-07-08T02:38:59Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 1,80p scripts/tpu/_remote_redeploy.sh


## 2026-07-08T02:38:26Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 700,760p /home/cataluna84/Workspace/tinyaya-stage2-scale/.venv/lib/python3.12/site-packages/torch_xla/distributed/spmd/xla_sharding.py


## 2026-07-08T02:25:59Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:479:    from torch_xla.experimental.scan_layers import (


## 2026-07-08T02:25:41Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v2.sh


## 2026-07-08T02:25:30Z | feat/v0.3-implementation@ab196fe | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2_v2.sh`


## 2026-07-08T02:24:46Z | feat/v0.3-implementation@ab196fe | done | exec
.venv/bin/ruff check src/model/scan_utils.py src/model/composite.py && .venv/bin/python -c "


## 2026-07-08T02:24:33Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-08T02:24:24Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-08T02:22:17Z | feat/v0.3-implementation@ab196fe | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2.sh


## 2026-07-08T02:22:10Z | feat/v0.3-implementation@ab196fe | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/watch_scan2.sh`


## 2026-07-08T02:19:48Z | feat/v0.3-implementation@ab196fe | done | exec
sed -n 1,80p scripts/tpu/launch_spot.sh


## 2026-07-08T02:19:39Z | feat/v0.3-implementation@ab196fe | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name.basename(),state.state)" 2>&1


## 2026-07-08T02:18:52Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/reval/smoke_scan.yaml`


## 2026-07-08T02:18:48Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/reval/smoke_scan.yaml`


## 2026-07-08T01:39:35Z | feat/v0.3-implementation@ab196fe | info | session
PreCompact (manual): 5 unchecked PLAN items

Top open items:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-08T01:39:24Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T20:01:21Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T19:54:47Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:398:    from torch_xla.experimental.scan_layers import (


## 2026-07-07T19:50:40Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:398:    from torch_xla.experimental.scan_layers import (


## 2026-07-07T19:50:08Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:49:28Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:398:    from torch_xla.experimental.scan_layers import (


## 2026-07-07T19:49:06Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:48:21Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/composite.py`


## 2026-07-07T19:47:20Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:44:19Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:398:    from torch_xla.experimental.scan_layers import (


## 2026-07-07T19:43:40Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:42:47Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-07T19:42:21Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-07T19:41:06Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:39:36Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:37:08Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:36:20Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:36:11Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-07T19:35:18Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-07T19:28:39Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T19:26:49Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:24:31Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:23:39Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/composite.py`


## 2026-07-07T19:23:19Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/composite.py`


## 2026-07-07T19:21:57Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:21:17Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:20:25Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:18:18Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:17:29Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:16:08Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:15:31Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:14:23Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T19:13:34Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T15:55:33Z | feat/v0.3-implementation@ab196fe | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T15:33:08Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:32:56Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/scan_utils.py`


## 2026-07-07T15:27:34Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:26:49Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:13:15Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:12:08Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:11:40Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:10:53Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T15:10:21Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:57:38Z | feat/v0.3-implementation@ab196fe | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T14:57:19Z | feat/v0.3-implementation@ab196fe | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-07T14:56:24Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:55:52Z | feat/v0.3-implementation@ab196fe | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:55:19Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:55:00Z | feat/v0.3-implementation@cb58b11 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/composite.py`


## 2026-07-07T14:53:51Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:52:49Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:48:29Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:48:09Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:47:53Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:42:38Z | feat/v0.3-implementation@cb58b11 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T14:40:59Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:39:57Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:39:18Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:29:21Z | feat/v0.3-implementation@cb58b11 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T14:28:44Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T14:25:01Z | feat/v0.3-implementation@cb58b11 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T14:24:39Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:58:26Z | feat/v0.3-implementation@cb58b11 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T13:57:40Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:56:56Z | feat/v0.3-implementation@cb58b11 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:56:21Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:55:56Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:39:37Z | feat/v0.3-implementation@7183b5e | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T13:38:00Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:36:13Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:34:38Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:33:34Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:32:40Z | feat/v0.3-implementation@7183b5e | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name,state.state)" 2>&1


## 2026-07-07T13:32:19Z | feat/v0.3-implementation@7183b5e | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T13:06:43Z | feat/v0.3-implementation@7183b5e | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T13:06:26Z | feat/v0.3-implementation@7183b5e | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/monitor_all_reval.sh


## 2026-07-07T13:06:06Z | feat/v0.3-implementation@7183b5e | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name,state.state)" 2>&1


## 2026-07-07T13:05:52Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:04:13Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:03:23Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:01:58Z | feat/v0.3-implementation@7183b5e | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T13:01:25Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:00:41Z | feat/v0.3-implementation@7183b5e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:00:21Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T13:00:11Z | feat/v0.3-implementation@257b449 | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_supervisor.sh`


## 2026-07-07T12:59:30Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale; sed -n '35,75p' scripts/tpu/launch_sweep_supervisor.sh


## 2026-07-07T12:59:24Z | feat/v0.3-implementation@257b449 | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/reval_supervisor.sh`


## 2026-07-07T12:58:27Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:57:49Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:56:42Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:55:58Z | feat/v0.3-implementation@257b449 | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/gate_scan.sh


## 2026-07-07T12:55:32Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:55:04Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:54:34Z | feat/v0.3-implementation@257b449 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:54:13Z | feat/v0.3-implementation@3bb635a | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/stage2_tpu_v6e8_reval.yaml`


## 2026-07-07T12:53:41Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:49:22Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:48:01Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:47:13Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T12:46:00Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:57:28Z | feat/v0.3-implementation@3bb635a | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T08:57:09Z | feat/v0.3-implementation@3bb635a | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/monitor_all_reval.sh


## 2026-07-07T08:56:31Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:55:49Z | feat/v0.3-implementation@3bb635a | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name,state.state)" 2>&1


## 2026-07-07T08:39:41Z | feat/v0.3-implementation@3bb635a | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T08:39:05Z | feat/v0.3-implementation@3bb635a | done | exec
bash /tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/monitor_reval.sh


## 2026-07-07T08:38:34Z | feat/v0.3-implementation@3bb635a | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/MEMORY.md`


## 2026-07-07T08:38:27Z | feat/v0.3-implementation@3bb635a | done | edit
created `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v03-reval-sweep-launch.md`


## 2026-07-07T08:37:28Z | feat/v0.3-implementation@3bb635a | done | exec
gcloud compute tpus queued-resources list --project=ml-pipelines-315702 --zone=europe-west4-a --format="table(name,acceleratorType,state)" 2>&1


## 2026-07-07T08:37:16Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:35:24Z | feat/v0.3-implementation@3bb635a | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:35:03Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:34:38Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:34:26Z | feat/v0.3-implementation@8a34ab9 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_arms.sh`


## 2026-07-07T08:34:06Z | feat/v0.3-implementation@8a34ab9 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_arms.sh`


## 2026-07-07T08:33:51Z | feat/v0.3-implementation@8a34ab9 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_arms.sh`


## 2026-07-07T08:33:39Z | feat/v0.3-implementation@8a34ab9 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_arms.sh`


## 2026-07-07T08:33:30Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:33:01Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:32:22Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:31:36Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:31:05Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:30:19Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:28:42Z | feat/v0.3-implementation@8a34ab9 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T08:28:17Z | feat/v0.3-implementation@8a34ab9 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:27:30Z | feat/v0.3-implementation@8a34ab9 | done | exec
git commit -m "feat(reval): v6e-8 reval base config + 6-arm generator/launcher (Phase 1 prep)


## 2026-07-07T08:27:15Z | feat/v0.3-implementation@aa5d3aa | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-07T08:27:03Z | feat/v0.3-implementation@aa5d3aa | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-reval-sweep-plan.md`


## 2026-07-07T08:26:40Z | feat/v0.3-implementation@aa5d3aa | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-reval-sweep-plan.md`


## 2026-07-07T08:25:55Z | feat/v0.3-implementation@aa5d3aa | done | exec
python3 -c "


## 2026-07-07T08:25:27Z | feat/v0.3-implementation@aa5d3aa | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_reval_arms.sh`


## 2026-07-07T08:24:54Z | feat/v0.3-implementation@aa5d3aa | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-07T08:24:16Z | feat/v0.3-implementation@aa5d3aa | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/configs/tpu/stage2_tpu_v6e8_reval.yaml`


## 2026-07-07T08:20:52Z | feat/v0.3-implementation@aa5d3aa | done | exec
git add scripts/train_hierarchical.py && git commit -m "feat(sweep): expose --depth_unfreeze_blocks / --lr_depth_blocks CLI (reval arm F)


## 2026-07-07T08:19:17Z | feat/v0.3-implementation@7135d53 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/train_hierarchical.py`


## 2026-07-07T08:18:28Z | feat/v0.3-implementation@7135d53 | done | exec
git add scripts/report_capacity.py && git commit -m "feat(capacity): add scripts/report_capacity.py for v0.3 reval arm sizing


## 2026-07-07T08:17:58Z | feat/v0.3-implementation@cc3cc6f | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:17:21Z | feat/v0.3-implementation@cc3cc6f | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:17:08Z | feat/v0.3-implementation@cc3cc6f | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:16:39Z | feat/v0.3-implementation@cc3cc6f | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:16:27Z | feat/v0.3-implementation@cc3cc6f | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:12:25Z | feat/v0.3-implementation@cc3cc6f | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/report_capacity.py`


## 2026-07-07T08:11:15Z | feat/v0.3-implementation@cc3cc6f | done | exec
sed -n 55,105p /home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/make_splits.py


## 2026-07-07T08:10:08Z | feat/v0.3-implementation@cc3cc6f | done | exec
sed -n 1,160p /home/cataluna84/Workspace/tinyaya-stage2-scale/src/model/lora_setup.py


## 2026-07-07T08:08:03Z | feat/v0.3-implementation@cc3cc6f | done | exec
git add docs/v0.3-reval-sweep-plan.md docs/v0.3-public-release-plan.md && git commit -m "docs(v0.3): add approved 6-arm reval-sweep plan (long-horizon re-validation → production → eval)


## 2026-07-07T08:07:48Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-public-release-plan.md`


## 2026-07-07T08:07:40Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-reval-sweep-plan.md`


## 2026-07-07T08:07:23Z | feat/v0.3-implementation@5d57918 | done | exec
cp /home/cataluna84/.claude/plans/inherited-exploring-cherny.md /home/cataluna84/Workspace/tinyaya-stage2-scale/docs/v0.3-reval-sweep-plan.md


## 2026-07-07T08:04:48Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:04:39Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:04:27Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:04:20Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:04:08Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:04:02Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T08:03:54Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T07:58:47Z | feat/v0.3-implementation@5d57918 | done | edit
created `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-07T07:44:59Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T07:44:45Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T07:44:45Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T07:42:27Z | feat/v0.3-implementation@5d57918 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T07:42:13Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/MEMORY.md`


## 2026-07-07T07:42:06Z | feat/v0.3-implementation@5d57918 | done | edit
edited `/home/cataluna84/.claude/projects/-home-cataluna84-Workspace-tinyaya-stage2-scale/memory/v6e64-spot-prober-vm.md`


## 2026-07-07T07:41:20Z | feat/v0.3-implementation@5d57918 | done | exec
gcloud compute instances list --project=ml-pipelines-315702 2>&1


## 2026-07-07T07:41:09Z | feat/v0.3-implementation@5d57918 | done | exec
gcloud compute instances list --project=ml-pipelines-315702 --filter="name=tinyaya-v6e64-prober" --format="table(name,zone,status,machineType.basename())" 2>&1


## 2026-07-07T07:40:26Z | feat/v0.3-implementation@5d57918 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-07T07:39:59Z | feat/v0.3-implementation@5d57918 | done | exec
gcloud compute tpus queued-resources delete tinyaya-v6e16-sweep-ew4-qr --project=ml-pipelines-315702 --zone=europe-west4-a --force --quiet 2>&1


## 2026-07-07T07:39:25Z | feat/v0.3-implementation@5d57918 | done | exec
gcloud compute tpus queued-resources delete tinyaya-v6e8-overfit-qr --project=ml-pipelines-315702 --zone=europe-west4-a --force --quiet 2>&1


## 2026-07-07T07:34:43Z | feat/v0.3-implementation@5d57918 | info | session
PreCompact (manual): 5 unchecked PLAN items

Top open items:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T07:34:23Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (resume): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-07T07:33:53Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-06T11:41:31Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-06T02:32:41Z | feat/v0.3-implementation@5d57918 | info | session
SessionEnd (other): 5 item(s) carried forward

Next steps:
- v0.3 production run completes (14,532 steps / 3 epochs) on v6e-16; `best_by_val` chosen.
- Release eval with the loader-fixed path: per-codebook accuracy (teacher-forced),
- v0.3 HF repo published (card + all checkpoints); dataset cards note the no-alignments gap.
- Code repos opened; `THIRD_PARTY_NOTICES.md` covers the synthetic sources.
- Blog updated to the audio-only honest result; leaked tokens rotated before public.


## 2026-07-06T02:29:47Z | feat/v0.3-implementation@5d57918 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-06T02:29:21Z | feat/v0.3-implementation@5d57918 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:28:57Z | feat/v0.3-implementation@c5f8b8e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:28:45Z | feat/v0.3-implementation@c5f8b8e | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/do.md`


## 2026-07-06T02:28:08Z | feat/v0.3-implementation@c5f8b8e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:27:46Z | feat/v0.3-implementation@c5f8b8e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:27:27Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/ops.sh`


## 2026-07-06T02:27:26Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/setup_gcp.sh`


## 2026-07-06T02:27:13Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_spot.sh`


## 2026-07-06T02:26:51Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_spot.sh`


## 2026-07-06T02:26:45Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_spot.sh`


## 2026-07-06T02:26:33Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_spot.sh`


## 2026-07-06T02:26:21Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_spot.sh`


## 2026-07-06T02:25:59Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_canary.sh`


## 2026-07-06T02:25:42Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_qr.sh`


## 2026-07-06T02:25:20Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_release.sh`


## 2026-07-06T02:25:18Z | feat/v0.3-implementation@c5f8b8e | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/scripts/tpu/launch_release.sh`


## 2026-07-06T02:24:45Z | feat/v0.3-implementation@c5f8b8e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:23:42Z | feat/v0.3-implementation@c5f8b8e | done | edit
created `/home/cataluna84/.claude/plans/inherited-exploring-cherny.md`


## 2026-07-06T02:18:43Z | feat/v0.3-implementation@c5f8b8e | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-06T02:18:28Z | feat/v0.3-implementation@c5f8b8e | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:18:11Z | feat/v0.3-implementation@a16eac1 | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/docs/do.md`


## 2026-07-06T02:17:39Z | feat/v0.3-implementation@a16eac1 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:13:10Z | feat/v0.3-implementation@a16eac1 | fail | verify
verify: 11 passed, 1 failed out of 12 on Stop

FAIL [1] # the TPU↔GPU seam holds: torch_xla must NOT leak into shared model/data code
    src/model/scan_utils.py:125:        from torch_xla.experimental.scan_layers import scan_layers


## 2026-07-06T02:12:42Z | feat/v0.3-implementation@a16eac1 | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:12:08Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:11:45Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:11:20Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:10:57Z | feat/v0.3-implementation@ba2b0cc | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/agents/tpu-watchdog.md`


## 2026-07-06T02:10:24Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:10:05Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:09:41Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:09:31Z | feat/v0.3-implementation@ba2b0cc | done | edit
created `/tmp/claude-1000/-home-cataluna84-Workspace-tinyaya-stage2-scale/9d91a9c6-d22b-474c-8971-e137f68da904/scratchpad/memories_new.md`


## 2026-07-06T02:08:56Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:08:27Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## 2026-07-06T02:08:10Z | feat/v0.3-implementation@ba2b0cc | done | edit
edited `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/VERIFY.md`


## 2026-07-06T02:07:38Z | feat/v0.3-implementation@ba2b0cc | done | edit
created `/home/cataluna84/Workspace/tinyaya-stage2-scale/.claude/PLAN.md`


## 2026-07-06T02:06:58Z | feat/v0.3-implementation@ba2b0cc | done | exec
cd /home/cataluna84/Workspace/tinyaya-stage2-scale


## Current state — 2026-07-06

**Project:** TinyAya v0.3 — audio-only TR↔HI speech-to-speech translation on `feat/v0.3-implementation` (PR #10).

- **Recipe frozen** (capacity-sweep winner): LoRA **r=32, alpha=64, rsLoRA, +MLP** target
  modules, `lr_lora=1.716e-4`, `exclude_top=2`. Production config
  `configs/tpu/stage2_tpu_v6e16_full_v03.yaml` (14,532 steps = 3 epochs) on **v6e-16**.
- **Data:** synthetic `tr-hi-mimi-encoded` ~1.24M → 1,178,302 train / 62,036 val
  (audio-only; corpus ships no text alignments → `text_weight=0`).
- **Pipeline validated:** overfit gate memorizes all 8 codebooks (89–98%). The
  per-codebook accuracy metric bug (undelayed vs delayed target) fixed (`8854698`).
- **#71 fixed** (`eb17609`): TPU scan-wrapper adapter-load bug — eval loaded 1/239 LoRA
  tensors → ~19%; now 239/239, eval reconciles with training (97.3% vs 98.1% CB0), with a
  fidelity guard that raises on any unfilled LoRA tensor. Prior `eval_checkpoint.py`
  numbers vs TPU checkpoints were invalid.
- **Infra** (`ba2b0cc`): GCS bucket migrated us-central2 → **`gs://tinyaya-stage2-eu`**
  (europe-west4, co-located with TPUs), old bucket deleted (killed cross-region egress,
  ~98% of the bill). Obsolete sweep/opt/v2 checkpoints pruned (265 → 49.5 GiB); 3 keepers
  remain (`v6e16-smoke-r32`, `v6e16-b256`, `v6e8-overfit-r32`).
- **Docs pass** (this session): all `.md` updated to v0.3 reality + pruned; plan sprawl,
  MEMORY-* meta, and tpu-changes/launch-plan consolidated; this log archived.
- **Slices:** v6e-16 + v6e-8 idle/ACTIVE in europe-west4-a (TRC, do not tear down without intent).

**Next:** production run is **held** (launched then stopped) — relaunch when ready, then
eval (`scripts/eval_checkpoint.py`) → publish v0.3 card + checkpoints (see
`docs/v0.3-public-release-plan.md`). Rotate any leaked tokens before going public.

---
