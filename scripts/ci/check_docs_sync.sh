#!/usr/bin/env bash
# Docs-consistency guard: operative docs must not regress to the four
# staleness classes the 2026-07-15 repo-wide sync eliminated.
#
#   1. the "global batch 256" fiction stated as fact (the P0 batch-semantics
#      audit proved real optimizer batch = loader batch x accum = 32; any
#      mention of 256 must carry the audit footnote marker "batch-semantics")
#   2. the single-host config named as THE run config (the long-horizon run
#      is stage2_tpu_v6e16_full_v03_mh.yaml)
#   3. the retired step count "14,532 steps"
#   4. forward-looking "production run" framing (user directive 2026-07-14:
#      it is the LONG-HORIZON run; historical docs are exempt)
#
# Historical documents are exempt by omission from OPERATIVE_DOCS.
set -uo pipefail
cd "$(dirname "$0")/../.."

OPERATIVE_DOCS=(
    README.md
    AGENTS.md
    MODEL_CARD.md
    docs/hf-model-card-tr-hi-s2st-v0.3.md
    docs/tpu-runbook.md
    docs/onboarding.md
    docs/v0.3-public-release-plan.md
    scripts/tpu/README.md
    sweeps/README.md
)

fail=0

for doc in "${OPERATIVE_DOCS[@]}"; do
    [ -f "$doc" ] || continue
    # 1. unfootnoted batch-256 fiction (allow lines that carry the marker)
    if grep -nE 'global batch 256|batch[_ ]size:? 256' "$doc" | grep -vi 'batch-semantics' | grep -q .; then
        echo "FAIL[$doc]: 'global batch 256' without the batch-semantics footnote"
        grep -nE 'global batch 256|batch[_ ]size:? 256' "$doc" | grep -vi 'batch-semantics' | head -3
        fail=1
    fi
    # 2. old config named as the run config
    if grep -n 'stage2_tpu_v6e16_full_v03\.yaml' "$doc" | grep -q .; then
        echo "FAIL[$doc]: references the single-host config as the run config (use _mh.yaml)"
        fail=1
    fi
    # 3. retired step count
    if grep -n '14,532' "$doc" | grep -q .; then
        echo "FAIL[$doc]: retired step count 14,532 (long-horizon run = 110,463)"
        fail=1
    fi
    # 4. forward-looking production framing
    if grep -niE 'production (run|launch|training|config)' "$doc" | grep -q .; then
        echo "FAIL[$doc]: forward-looking 'production' framing (say: long-horizon run)"
        grep -niE 'production (run|launch|training|config)' "$doc" | head -3
        fail=1
    fi
done

if [ "$fail" -ne 0 ]; then
    echo "docs-sync check FAILED"
    exit 1
fi
echo "OK: operative docs consistent (batch semantics, run config, step count, naming)"
