# TRC TPU allocation -- authoritative record

## 2026-07-06 update

Current production path: **v6e-16 spot in `europe-west4-a`** (4 hosts × 4 chips = one
16-chip SPMD mesh) for the v0.3 run; a **v6e-8** (single host) in the same zone is used
for smoke / overfit / eval. Both are carved from the 64-chip v6e spot quota rows below.
Checkpoints → `gs://tinyaya-stage2-eu` (europe-west4). The v6e-64 lines proved
un-gettable on spot (both zones failed repeatedly); v4/v5e rows are legacy.
The allocation table below is the authoritative quota grant; day-to-day work uses the
v6e rows in `europe-west4-a` / `us-east1-d`. See [`tpu-runbook.md`](tpu-runbook.md) for launch.

**Status:** Active
**Captured:** 2026-05-05
**Recipient:** `mayankbhaskar007@gmail.com`
**GCP project:** `ml-pipelines-315702`
**Grant duration:** 90 days (free Cloud TPU usage; non-TPU GCP services
still billed; Google may reclaim capacity at any time)
**Source:** TRC welcome email from `trc-support@google.com` (subject
"You have access to free Cloud TPUs"), pasted by the user on
2026-05-05 and archived verbatim in this document.

This file is the **single source of truth** for which TPU types,
zones, and tiers we are entitled to.

---

## 1. Allocation table

| Quantity | TPU type | Zone | Tier |
|---:|---|---|---|
| 32 chips | Cloud TPU v4 | `us-central2-b` | **spot** |
| 32 chips | Cloud TPU v4 | `us-central2-b` | **on-demand** |
| 64 chips | Cloud TPU v5e | `europe-west4-b` | spot |
| 64 chips | Cloud TPU v5e | `us-central1-a` | spot |
| 64 chips | Cloud TPU v6e | `europe-west4-a` | spot |
| 64 chips | Cloud TPU v6e | `us-east1-d` | spot |

The dual v4 lines in `us-central2-b` are independent quotas: 32 chips
of on-demand AND 32 chips of spot in the same zone.
`v6e-8-eu` is a smaller single-host slice requested against the v6e
spot capacity in `europe-west4-a`; it is not a separate TRC grant row.

### Profile shorthands

`scripts/tpu/launch_spot.sh` accepts the following `TRC_PROFILE`
values, each mapping to a single row above:

| `TRC_PROFILE` | TPU type passed to `gcloud` | Zone | Notes |
|---|---|---|---|
| `v6e-8-eu` | `v6e-8` | `europe-west4-a` | Single-host 8-chip slice for smoke / overfit / eval; avoids multi-host rendezvous. |
| `v4-32-uc2b` | `v4-32` | `us-central2-b` | Same zone as on-demand v4 quota; smallest legacy v4 fallback. |
| `v5e-64-ew4b` | `v5litepod-64` | `europe-west4-b` | Largest v5e slice; matches v5litepod-* canary tuning. |
| `v5e-64-uc1a` | `v5litepod-64` | `us-central1-a` | Same chip family as `v5e-64-ew4b`, US zone. |
| `v6e-64-ew4a` | `v6e-64` | `europe-west4-a` | Newest gen; needs `v2-alpha-tpuv6e` runtime. |
| `v6e-64-ue1d` | `v6e-64` | `us-east1-d` | Same as above, US zone. |

The on-demand v4 quota does not need a profile here -- it is already
the default of `scripts/tpu/launch_qr.sh` (no `--spot`).

## 2. Important caveats (verbatim from the email)

> This free 90-day trial is only available for new Cloud TPUs you
> create in the zones listed above. To avoid charges, please be sure
> to create your Cloud TPUs in the appropriate zone.

> While your Cloud TPUs are free, you'll still be charged for the
> rest of the GCP services you use. If you have a new account, Google
> Cloud's $300 USD introductory credit may completely offset these
> costs, and you can minimize costs even more by utilizing the new
> Cloud TPU VM architecture.

> Please note that demand for Cloud TPUs is high, so we can't
> guarantee you'll get to use all of your TPU quota. Google reserves
> the right to reclaim TRC quota and TRC Cloud TPU capacity at any
> time.

> If you have access to both on-demand and preemptible quotas, we
> recommend preferring on-demand and falling back to preemptible
> if/when on-demand is not available.

> If you have access to v2-8 and/or v3-8 quotas, please be aware
> that these individual devices cannot be used in pod configurations.
> *(Not applicable to this grant -- no v2/v3 quotas.)*

> If you encounter an error message indicating that your quota is
> exhausted, confirm that you have deleted any unused Cloud TPUs
> and/or Queued Resources that may still be consuming quota.

## 3. How to pick a zone (decision tree)

```text
Is the on-demand v4 quota in us-central2-b free right now?
+-- Yes -> use the on-demand path (existing launch_qr.sh defaults; no --spot)
+-- No  -> launch_spot.sh; pick TRC_PROFILE based on goal:
          +-- "I want minimal infra change" .................. v4-32-uc2b (default)
          +-- "I want maximum throughput on v5e family" ...... v5e-64-ew4b
          +-- "I am US-based and want low latency" ........... v5e-64-uc1a OR v6e-64-ue1d
          +-- "I want the validated production path" ......... v6e-8-eu
          +-- "I want to test newest multi-host hardware" .... v6e-64-ew4a OR v6e-64-ue1d
          +-- "Probe / smoke test only, smallest cost" ....... v4-32-uc2b (still smallest in this grant)
```

**Operational default for this repo's active TPU work:** `v6e-16-eu` for the production
run, `v6e-8-eu` for smoke / overfit / eval — both in `europe-west4-a`, both from the v6e
spot quota. Set `TRC_PROFILE` explicitly per goal.

## 4. Program requirements (we accepted these)

Per the welcome email, TRC participants are expected to:

- Share TRC-supported research with the world (peer-reviewed
  publications, open-source code, blog posts, or other means).
- Share detailed feedback with Google to help improve the TRC
  program and the underlying Cloud TPU platform.
- Conduct research in accordance with the Google AI Principles.
- Accept Google's Terms and Conditions.
- Acknowledge that the participant's information will be used
  in accordance with Google's Privacy Policy.

Acknowledged. Outputs from this repo (code, blog post, eval results)
are intended to satisfy the publication requirement.

## 5. Support

- Email: `trc-support@google.com`.
- Discord: `#tpu-research-cloud` channel on the Google Developer
  Community Discord server.
- Recommended reading: PyTorch/XLA performance debugging blog series (Parts I-III).

## 6. Footer (verbatim from the email)

> Google LLC 1600 Amphitheatre Parkway, Mountain View, CA 94043
>
> This email was sent to `mayankbhaskar007@gmail.com` to update you
> about important information regarding your Google Cloud Platform
> account.

## 7. Cross-references

- [`tpu-runbook.md`](tpu-runbook.md) -- current launch / resume / staging.
- `.claude/memories.md` -- "TRC allocation captured" decision entry (2026-05-05).
- `scripts/tpu/launch_spot.sh` -- materialises the `TRC_PROFILE` shorthands into `gcloud` flags.
