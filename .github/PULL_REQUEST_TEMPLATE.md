## What & why

<!-- What changes, and what problem it solves. Link any issue. -->

## Checks

<!-- These are the gates CI runs; see CONTRIBUTING.md. -->

- [ ] `uv run python -m pytest tests/ -q` passes
- [ ] `uv run ruff check .` is clean
- [ ] `bash scripts/ci/check_backend_seam.sh` passes — no module-level
      `import torch_xla` outside `src/backend/tpu_backend.py`
- [ ] `bash scripts/ci/check_docs_sync.sh` passes — if I changed an operative
      number (batch semantics, step counts, run config), I changed it
      everywhere

## Evidence

<!-- CONTRIBUTING requires evidence for these; delete the rows that don't apply. -->

- **Recipe change** (LR, LoRA config, batch, schedule, loss weights) → link the
  sweep/probe run that justifies it:
- **Trainer change that could affect numerics** → link a smoke run or the
  memorization gate showing parity:
- **Metric/logging change** → the test that pins the new behaviour:

## Published-artifact impact

<!-- Say so explicitly if this changes checkpoint layout, W&B keys, hub
     structure, or anything a downstream consumer of the released model
     depends on. Write "none" if it doesn't. -->

none
