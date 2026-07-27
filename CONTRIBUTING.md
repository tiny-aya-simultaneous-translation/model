# Contributing

Thanks for your interest in TinyAya Stage 2 (TR↔HI speech-to-speech
translation). This is a research codebase with a few hard rules that keep the
dual-backend (GPU/TPU) training stack reproducible — please read them before
opening a PR.

## Dev setup

```bash
uv sync                    # python 3.12; deps from uv.lock (frozen)
uv sync --extra eval       # + evaluation deps (see docs/evals-runbook.md)
```

- **transformers is pinned to 4.49.x** — 4.57+/5.x break the Cohere2 and
  Moshi model code this project patches (proven live). Do not bump it in a PR
  without a full pipeline re-validation.
- Two eval tools (`unbabel-comet`, `sonar-space`) cannot co-resolve with the
  training pins; they live in a standalone venv (procedure in
  `docs/evals-runbook.md`), not in `pyproject.toml`.

## Credentials (`.env`)

Secrets live in a gitignored repo-root `.env`. Start from the template:

```bash
cp example.env .env      # then fill in your own values
```

`example.env` documents every variable; the short version:

| variable | when you need it |
|---|---|
| `HF_TOKEN` | **required** — pulls the gated `CohereLabs/tiny-aya-base`; `setup_gcp.sh` aborts without it |
| `WANDB_API_KEY` + `WANDB_PROJECT` / `WANDB_ENTITY` | recommended — training runs without it but logs nothing |
| `GEMINI_API_KEY` | release evals only (the GEMBA judge + ASR referee stage) |
| `PROJECT_ID` / `REGION` / `BUCKET` | optional GCP overrides; defaults reproduce the published run |

Shell scripts load `.env` through `load_env_file` (`scripts/tpu/_lib.sh`) with
precedence **shell env > `.env` > script defaults**. Python entrypoints read the
process environment, so export first (`set -a; . ./.env; set +a`).

Two rules, both non-negotiable:

- **Never commit real values.** Every `*.env` is gitignored (plus `.envrc` and
  `*-key.json` / `service-account*.json` / `credentials.json`); `example.env` is
  the one tracked exception. On TPU, `setup_gcp.sh` pushes `HF_TOKEN` /
  `WANDB_API_KEY` into GCP Secret Manager and the workers fetch them at boot —
  keys never land in a VM image, a config, or a log.
- **Keep secrets out of logs.** If you add a code path that echoes environment
  or command lines, check it against the scrubber in
  `.claude/hooks/_lib.py::scrub` and `scripts/tpu/launch_release.sh`'s log
  sanitizer.

Per-run launch settings (slice, recipe, corpus URIs) are *not* credentials and
are *not* read from `.env` — pass them to `scripts/tpu/launch_spot.sh` on the
command line. Saving them to a gitignored `launch.env` is optional and serves one
purpose: `scripts/tpu/qr_watch.sh` (the only consumer) re-sources that file to
replay an identical relaunch after a spot preemption. See `docs/tpu-runbook.md`.

## The rules CI enforces

Run these locally before pushing — the `seam-and-syntax` workflow runs them
on every PR:

```bash
uv run python -m pytest tests/ -q        # must pass (CI runs a bare venv:
                                         #  heavy imports must stay lazy)
uv run ruff check .                      # do not add NEW findings
bash scripts/ci/check_backend_seam.sh    # TPU/GPU seam (below)
bash scripts/ci/check_docs_sync.sh       # operative docs consistency
```

1. **The TPU↔GPU seam**: `import torch_xla` is allowed ONLY in
   `src/backend/tpu_backend.py`. Everything in `src/` and
   `scripts/train_hierarchical.py` must run on both backends. TPU launch
   tooling lives in `scripts/tpu/`, TPU configs in `configs/tpu/`.
2. **Lazy imports in shared code**: CI installs only `pytest pyyaml` — tests
   use `importorskip` for torch/sacrebleu/etc., and library imports in
   `src/evaluation/` are deferred to call time. Keep it that way.
3. **Docs sync**: operative numbers (batch semantics, step counts, run
   config) are cross-checked between configs and docs by
   `check_docs_sync.sh`. If you change one, change the other.

## Code style

Follow the TPU-for-GPU-engineers documentation style described in
`AGENTS.md` ("TPU code documentation style"): module docstrings explain WHY
the code exists and what XLA constraint shaped it; comments state
constraints, not narration. `ruff` is the formatter/linter of record.

## What needs evidence

- **Recipe changes** (LR, LoRA config, batch, schedule, loss weights): the
  current recipe is the winner of a multi-arm sweep + probe program. PRs that touch it need comparable sweep
  evidence, not vibes.
- **Trainer changes that could affect numerics**: cite a smoke run (the
  configs under `configs/tpu/` with `max_steps` ≤ 2000) or a memorization
  gate (`tests/` + the overfit config) showing parity.
- **Metric/logging changes**: pin the new behavior in
  `tests/test_hardening_prelaunch.py` (see `test_release_metric_wiring`).

## PRs

- Branch from `main`, keep PRs focused, make CI green.
- Disclose anything that changes published-artifact semantics (checkpoint
  layout, W&B keys, hub structure) in the PR description.
- Model weights are CC-BY-NC-4.0 (base-model inheritance); code
  contributions are accepted under Apache-2.0. See `THIRD_PARTY_NOTICES.md`.
