# Security Policy

## Supported versions

This is a **research** codebase. Only the latest release on `main` receives
fixes; older tags are historical artifacts of the training program and are not
patched.

| Version | Supported |
|---|---|
| `v0.3` / `main` | ✅ |
| `v0.2`, `v0.1` | ❌ (historical) |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately via
[GitHub Security Advisories](https://github.com/tiny-aya-simultaneous-translation/model/security/advisories/new).
If that is unavailable to you, contact a maintainer listed in `NOTICE`.

Please include: what you found, how to reproduce it, and the impact you expect.
We will acknowledge receipt and keep you updated on remediation.

## Scope

In scope:

- Credential handling in the training/eval tooling (`scripts/tpu/*`,
  `scripts/eval_release.py`, the `.env` loading path in `scripts/tpu/_lib.sh`).
- Anything that could cause a secret to be written to a log, a checkpoint, a
  W&B run, or the git history.
- Supply-chain concerns in the pinned dependency set (`pyproject.toml`,
  `uv.lock`).

Out of scope:

- The behaviour or outputs of the released **model weights**. This is a
  research speech-translation model: it is not robust, not safety-tuned, and
  its generated audio is documented as low-fidelity. Model quality issues are
  ordinary bugs — open a normal issue.
- Vulnerabilities in upstream projects (PyTorch, transformers, Moshi/Mimi,
  the base model). Report those to their maintainers; tell us if we need to
  pin around them.

## Handling secrets in this repo

Credentials never belong in the repository:

- Every `*.env` is gitignored (`example.env` is the only tracked template),
  along with `.envrc` and common credential blobs.
- On TPU, `scripts/tpu/setup_gcp.sh` pushes `HF_TOKEN` / `WANDB_API_KEY` into
  GCP Secret Manager; workers fetch them at boot, so keys never land in a VM
  image or a config.
- `scripts/tpu/launch_release.sh` sanitizes logs (token patterns redacted,
  home paths stripped) before uploading them to GCS.

If you believe a secret has been committed, report it privately as above so it
can be rotated before any public discussion.
