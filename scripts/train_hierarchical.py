"""Train TinyAyaMoshiComposite with hierarchical codebook generation.

WHY THIS EXISTS
---------------
This is the canonical Stage 2 training entry point. It runs in three
mutually exclusive modes:

* **GPU single-process** -- the script just runs (no ``torchrun``).
* **GPU multi-process** -- launch with ``torchrun`` for DDP. The
  ``backend.init_distributed()`` call detects this via env vars.
* **TPU SPMD** -- one Python process per host (each host drives all
  4 chips). The ``backend.init_distributed()`` call sets up the XLA
  ``Mesh`` and the SPMD partitioner.

GPU vs TPU at a glance
----------------------
* On GPU we move data to ``device`` and call ``model(...)``. PyTorch
  schedules the kernels and CUDA streams hide latency.
* On TPU we *also* call ``model(...)`` -- but the first time XLA
  *traces* the whole forward+backward, *compiles* it to TPU machine
  code, and only then *executes* it. The compiled binary is reused
  for every subsequent step, so the first step is slow (minutes) and
  the rest are fast.
* On TPU we additionally call ``backend.mark_sharding(...)`` on the
  inputs so the SPMD partitioner knows the batch dimension is
  sharded across chips. GPU analogue: ``DistributedSampler`` (but
  here SPMD does it without per-rank Python state).

Config precedence
-----------------
YAML (``--config``) provides the defaults; CLI flags override; the
``DEFAULTS`` dict at the top of the file is the ultimate fallback.
Two new keys plumb the scan_layers / grad-checkpoint feature flags:

* ``train.use_scan_layers`` (bool) -- swap layer stacks for the
  ``scan_utils`` proxy. See PLAN.md Phase 1.
* ``train.xla_grad_checkpoint`` (bool) -- per-layer
  ``torch.utils.checkpoint``. See PLAN.md Phase 2.
* ``train.compile_warmup_steps`` (int) -- run zero-LR TPU macro-steps
  before visible step 1 so the counted loss curve starts after compile.
"""

import argparse
import contextlib
import json
import math
import os
import sys
import time
import warnings
from collections import deque
from pathlib import Path

# Our own code is fully migrated from the deprecated xm.mark_step() to
# torch_xla.sync() (2026-07-09; identical semantics in torch_xla 2.9). This
# filter is a safety net for torch_xla-INTERNAL callers (e.g.
# xm.optimizer_step) that still emit "Use torch_xla.sync instead" on every
# call -- with 8 micro graph-breaks per macro-step that used to spam hundreds
# of warning lines per logged step into /tmp/train.log. Filter BEFORE
# importing torch (torch_xla autoloads via torch's backend entry point).
warnings.filterwarnings("ignore", message=r"Use torch_xla\.sync instead")

# ruff: noqa: E402,I001
import soundfile as sf
import torch
import yaml
from torch.utils.data.distributed import DistributedSampler


def _patch_attention_mask_for_bf16() -> None:
    """Replace HF attention mask `torch.finfo(dtype).min` with safe -1e4.

    pytorch/xla #4152: HF transformers builds attention masks using
    `torch.finfo(fp32).min = -3.4e38`; when downcast to bf16 this becomes
    `-inf`, then `(1 - mask) * -inf = NaN`. Replacing the constant with
    -1e4 (well within bf16 representable range, still < softmax cutoff)
    avoids the overflow without changing model semantics.

    Idempotent. Must be called before any model loads.
    """
    try:
        from transformers.modeling_attn_mask_utils import AttentionMaskConverter
    except ImportError:
        return

    import transformers.modeling_attn_mask_utils as _mask_utils

    original_to_4d = AttentionMaskConverter.to_4d
    original_make_causal = AttentionMaskConverter._make_causal_mask

    SAFE_MIN = -1e4

    def patched_to_4d(self, attention_mask_2d, query_length, dtype, key_value_length=None):
        out = original_to_4d(self, attention_mask_2d, query_length, dtype, key_value_length)
        return out.clamp(min=SAFE_MIN)

    @staticmethod
    def patched_make_causal(
        input_ids_shape, dtype, device, past_key_values_length=0, sliding_window=None
    ):
        out = original_make_causal(
            input_ids_shape,
            dtype,
            device,
            past_key_values_length=past_key_values_length,
            sliding_window=sliding_window,
        )
        return out.clamp(min=SAFE_MIN)

    @staticmethod
    def patched_ignore_causal_mask_sdpa(
        attention_mask,
        inputs_embeds,
        past_key_values_length,
        sliding_window=None,
        is_training=False,
    ):
        # TPU note: HF's default implementation calls
        # `torch.all(attention_mask == 1)` and elides the 4D SDPA mask
        # for all-full batches. On XLA that value-dependent branch can
        # split the graph mid-run; keep one mask topology for every
        # batch instead.
        return False

    def patched_prepare_4d_attention_mask_for_sdpa(mask, dtype, tgt_len=None):
        return AttentionMaskConverter._expand_mask(mask=mask, dtype=dtype, tgt_len=tgt_len).clamp(
            min=SAFE_MIN
        )

    AttentionMaskConverter.to_4d = patched_to_4d
    AttentionMaskConverter._make_causal_mask = patched_make_causal
    if hasattr(AttentionMaskConverter, "_ignore_causal_mask_sdpa"):
        AttentionMaskConverter._ignore_causal_mask_sdpa = patched_ignore_causal_mask_sdpa
    if hasattr(_mask_utils, "_prepare_4d_attention_mask_for_sdpa"):
        _mask_utils._prepare_4d_attention_mask_for_sdpa = patched_prepare_4d_attention_mask_for_sdpa

    # Cohere2 (transformers 4.49) does NOT use AttentionMaskConverter -- it
    # builds its 4D causal mask in
    # Cohere2Model._prepare_4d_causal_attention_mask_with_cache_position
    # filled with torch.finfo(dtype).min. On XLA bf16, a fully-masked query
    # row (heavy validation padding) softmaxes over all-finfo.min -> 0/0 =
    # NaN. The AttentionMaskConverter patch above never covered this path,
    # which is why training (less intra-batch padding) was finite but the
    # padded validation batches went NaN. Clamp Cohere2's mask to -1e4 too:
    # for any row with >=1 valid key the softmax is unchanged; only the
    # all-masked rows become uniform (finite) instead of NaN.
    cohere_patched = False
    try:
        from transformers.models.cohere2 import modeling_cohere2 as _c2

        for _cls_name in ("Cohere2Model", "Cohere2ForCausalLM"):
            _cls = getattr(_c2, _cls_name, None)
            fn = getattr(_cls, "_prepare_4d_causal_attention_mask_with_cache_position", None)
            if _cls is None or fn is None:
                continue
            _orig = fn.__func__ if isinstance(fn, staticmethod) else fn

            def _patched_prep(*args, __orig=_orig, **kwargs):
                out = __orig(*args, **kwargs)
                if isinstance(out, torch.Tensor) and out.is_floating_point():
                    out = out.clamp(min=SAFE_MIN)
                return out

            _cls._prepare_4d_causal_attention_mask_with_cache_position = staticmethod(_patched_prep)
            cohere_patched = True
    except Exception as exc:  # pragma: no cover - depends on transformers version
        print(f"[bf16-mask-patch] Cohere2 mask patch skipped: {exc!r}", flush=True)

    print(
        "[bf16-mask-patch] AttentionMaskConverter patched "
        f"(clamp >= -1e4; SDPA mask elision disabled; cohere2={cohere_patched})",
        flush=True,
    )


_patch_attention_mask_for_bf16()


sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backend import get_backend
from src.data.bucket_sampler import BucketedMacroBatchSampler, normalize_buckets
from src.data.collator import InterleavedCollator
from src.data.dataset import StreamingTranslationDataset, TranslationDataset
from src.model.backbone import TinyAyaBackbone
from src.model.composite import TinyAyaMoshiComposite
from src.model.lora_setup import apply_lora
from src.training.checkpointing import (
    prune_checkpoints,
    push_checkpoint_to_hub,
    save_checkpoint,
)
from src.training.scheduler import WarmupCosineScheduler, WSDScheduler
from src.training.codebook_schedule import codebook_weights
from src.training.early_stop import early_stop_step
from src.training.multitask import composite_val_loss, text_weight_at
from src.training.param_classify import classify_param, depth_block_layer_index
from src.training.translation_loss import compute_hierarchical_translation_loss


_FSDPV2_BARRIER_TARGET_CLASSES: tuple[str, ...] = (
    "Cohere2DecoderLayer",
    "CohereDecoderLayer",
    "MoshiDecoderLayer",
)


def _streaming_effective_frame_lengths(
    dataset: StreamingTranslationDataset,
    *,
    max_frames: int,
) -> list[int]:
    """Read encoded tensor shapes and return post-truncation frame lengths."""
    lengths: list[int] = []
    for row in dataset.rows:
        pt_path = dataset._resolve(row["pt_path"])
        try:
            data = torch.load(pt_path, weights_only=False, mmap=True, map_location="cpu")
        except (TypeError, RuntimeError):
            data = torch.load(pt_path, weights_only=False, map_location="cpu")
        src_len = int(data["src_codes"].shape[1])
        tgt_len = int(data["tgt_codes"].shape[1])
        total = src_len + tgt_len
        effective = min(total, max_frames)
        if src_len > max_frames - 1:
            effective = max_frames
        lengths.append(effective)
    return lengths


def _apply_fsdpv2_backward_barriers(model: torch.nn.Module) -> int:
    """Register per-layer XLA optimization barriers on an SPMD model.

    Walks every submodule of ``model`` and, for each transformer
    decoder layer matched by class name, registers a backward hook
    that calls ``xm.optimization_barrier_`` over the layer's grads
    plus the upstream ``grad_input``. This forces XLA to materialise
    gradients and free the all-gather output of that layer's
    sharded full params before the previous layer's backward begins.

    Parameters
    ----------
    model : torch.nn.Module
        The composite, post-``backend.wrap_model``. ``SpmdFullyShardedDataParallel``
        does not wrap inner layers in nested FSDPv2 instances --
        instead it walks the auto_wrap_policy match set and applies
        ``xs.mark_sharding`` to each matched layer's parameters.
        Inner layers therefore remain ordinary
        ``CohereDecoderLayer`` / ``MoshiDecoderLayer`` instances,
        which is what we hook by class name here.

    Returns
    -------
    int
        Number of layers that received a barrier hook. Zero on
        non-TPU paths (the imports fail) and zero when the composite
        is missing both target layer classes.

    Notes
    -----
    TPU note: Without this hook, XLA's ``cache_all_gather=True``
    (defaulted in the SPMD partitioner; see openxla/xla #20508)
    retains the all-gather output of every sharded layer's full
    params from forward through backward. Across 36 sharded
    ``CohereDecoderLayer`` instances those retained ring buffers
    accumulate to ~28 GiB on v6e-8 (32 GiB / chip), which then
    deterministically OOMs around step 258 the moment XLA's CSE
    stops eliding equivalent all-gather ops and is forced to
    materialise the full ring of 20+ buffers simultaneously.

    The hook implements step 5 of the FSDPv2 SPMD recipe from
    pytorch/xla #6379 (the HF Llama 2 / DeepSeek SPMD reference
    pattern): a backward hook that calls
    ``xm.optimization_barrier_(grads + grad_input)`` per layer,
    forcing XLA to insert a fence that prevents the all-gather
    cache from accumulating across the forward-to-backward
    boundary.

    GPU analogue: none -- on GPU, FSDP's pre/post-backward hooks
    already free full params at exit; XLA SPMD requires this manual
    fence because the partitioner is far more aggressive about
    fusion + caching.

    References
    ----------
    openxla/xla #20508 -- ``cache_all_gather`` default + no flag.
    pytorch/xla #6379  -- FSDPv2 RFC step 5 (per-layer barrier).
    pytorch/xla #8423  -- SDPA 2.5x SPMD memory regression context.
    """
    try:
        from torch_xla.distributed.spmd.xla_sharding import (
            apply_backward_optimization_barrier,
        )
    except ImportError as exc:
        print(f"[fsdpv2] WARN: backward barrier unavailable: {exc!r}", flush=True)
        return 0

    barrier_count = 0
    for sub in model.modules():
        if type(sub).__name__ in _FSDPV2_BARRIER_TARGET_CLASSES:
            apply_backward_optimization_barrier(sub)
            barrier_count += 1
    print(
        f"[fsdpv2] applied backward optimization barrier to {barrier_count} layers "
        f"(targets={_FSDPV2_BARRIER_TARGET_CLASSES})",
        flush=True,
    )
    return barrier_count


# ---------------------------------------------------------------------------
# config loading
# ---------------------------------------------------------------------------

DEFAULTS = {
    "backend": "auto",
    "data": {
        "train_split": None,
        "val_split": None,
        "encoded_dir": None,
        "max_frames": 300,
        "bucket_frames": None,
        "audio_frame_rate": 12.5,
        "num_workers": 4,
        "pin_memory": True,
    },
    "train": {
        "num_codebooks": 8,
        "batch_size": 1,
        "grad_accum": 1,
        "max_steps": 3000,
        "warmup_steps": 200,
        "min_lr_ratio": 0.1,
        "depth_chunk_size": 16,
        "precision": "bfloat16",
        "max_grad_norm": 1.0,
        # One seed drives torch RNG (LoRA init, dropout) AND the bucket
        # sampler's data order. Change it for replicate probes (noise-floor
        # measurement); leave at 42 for anything meant to be comparable to
        # the v0.3 arms.
        "seed": 42,
        # Cosine horizon for WarmupCosineScheduler; null -> max_steps. Set it
        # LONGER than max_steps for probes that must ride an existing run's
        # exact lr trajectory and merely stop early — round-1 probes were
        # confounded because max_steps both ended the run and compressed the
        # schedule.
        "scheduler_total_steps": None,
        # TPU-SPMD batch sizing (P0 audit 2026-07-12): the LOGICAL global
        # batch is the loader tensor's batch dim -- chips do NOT multiply
        # data. per_chip_batch makes the intent explicit: the loader batch
        # resolves to per_chip_batch x chips (single-host only). When null,
        # batch_size is used as-is (legacy: batch_size IS the global batch).
        "per_chip_batch": None,
        # LR schedule shape: "cosine" (validated default) or "wsd"
        # (warmup-stable-decay -- peak plateau + short linear anneal; the
        # early-stop-friendly shape for the long-horizon run). WSD anneal
        # length: wsd_anneal_steps wins, else wsd_anneal_frac of the horizon.
        "schedule": "cosine",
        "wsd_anneal_steps": None,
        "wsd_anneal_frac": 0.1,
        "weight_decay": 0.01,
        "adam_beta1": 0.9,
        "adam_beta2": 0.999,
        "adam_eps": 1e-8,
        # Resume with a MISSING optimizer.pt is a hard error by default: a
        # long run must never silently continue on fresh Adam moments. Flip
        # to true only for a deliberate weights-only warm start.
        "allow_fresh_optimizer": False,
        # TPU-only flags. Both safe to leave True on GPU: the
        # scan proxy falls back to a plain loop, and the grad
        # checkpoint shim falls back to a direct call.
        "use_scan_layers": False,
        "xla_grad_checkpoint": False,
        "compile_warmup_steps": 0,
        # One-shot print of the first input batch's XLA sharding annotation
        # (P0 batch-semantics audit). Metadata-only; no per-step cost.
        "debug_input_sharding": False,
    },
    "loss": {"text_weight": 0.1, "audio_weight": 1.0},
    "optim": {
        "lr_lora": 1.5e-4,
        "lr_full_ft": 5e-5,
        "lr_projection": 5e-4,
        "lr_depth": 2.5e-4,
        "lr_audio_embed": 5e-4,
        "lr_text_embed": 5e-4,
    },
    "logging": {
        "log_every": 20,
        "save_every": 1000,
        "audio_every": 1000,
        "val_every": 1000,
        "val_max_batches": 50,
        # Inline validation on TPU is opt-in and WORKS (verified live on the
        # v0.3 reval arms + round-2 probes via XLA_NO_SPECIAL_SCALARS=1 +
        # nan_to_num). Default stays off so bare smoke configs skip the extra
        # compile; production/probe configs set true. On GPU, val always runs.
        "val_on_tpu": False,
        # TPU-SPMD-only: decouple the val loader batch from the locked train
        # batch (val is inference-only; bigger batches only shorten the val
        # cycle). None => val batch == train batch.
        "val_per_chip_batch": None,
        "save_dir": "checkpoints/stage2_scale",
        # Log-spaced early checkpoints for the public mech-interp suite (in
        # ADDITION to save_every). log_spaced_saves auto-adds {1,2,4,...,512};
        # save_at_steps is an explicit extra list. Empty/false => save_every only.
        "log_spaced_saves": False,
        "save_at_steps": None,
        # Background the periodic-save GCS upload so keep-all saves don't stall
        # training (best_by_val/final stay synchronous). Drained before final save.
        "async_checkpoint_upload": False,
        "wandb_project": "tinyaya-s2s",
        "wandb_run_name": "stage2_scale",
        "use_wandb": False,
        "push_to_hub": False,
        "hub_repo_id": None,
    },
    "perf": {
        "enabled": False,
        "warmup_skip_steps": 50,
        "xprof_trace_labels": False,
    },
}


def resolve_loader_batch(train_cfg: dict, n_chips: int, n_hosts: int) -> int:
    """Resolve the PER-HOST DataLoader batch size under TPU SPMD.

    The P0 batch-semantics audit (2026-07-12, scripts/tpu/spmd_batch_truth.py
    on a live mesh) proved the logical batch is the loader tensor's batch dim
    (``mark_sharding`` distributes rows, does not multiply them). So the loader
    each host builds must carry ``per_chip_batch`` rows for each of its LOCAL
    chips: ``per_chip_batch x (n_chips // n_hosts)``.

    * Single-host (n_hosts=1): per-host == global == ``per_chip x n_chips``
      (v6e-8: unchanged; the DataLoader tensor IS the global batch).
    * Multi-host (n_hosts>1): per-host == ``per_chip x local_chips`` (v6e-16:
      2 x 4 = 8). A ``DistributedSampler`` gives each host DISTINCT rows and
      ``backend.shard_to_device`` (minibatch=True) assembles the global batch
      ``per_host x n_hosts`` across hosts. The old multi-host REFUSAL is gone
      now that the minibatch pipeline exists.

    Returns ``batch_size`` unchanged when ``per_chip_batch`` is unset (legacy
    semantics: batch_size IS the per-host/global batch).
    """
    pcb = train_cfg.get("per_chip_batch")
    if not pcb:
        return int(train_cfg["batch_size"])
    local_chips = int(n_chips) // max(1, int(n_hosts))
    return int(pcb) * local_chips


def _percentile(values: list[float], q: float) -> float | None:
    """Return a percentile from an in-memory scalar window.

    Args:
        values: Finite scalar values already materialized on host.
        q: Percentile as a 0-1 fraction.

    Returns:
        The interpolated percentile, or ``None`` when ``values`` is
        empty.

    Notes:
        TPU note: callers append only host-side wall-clock values that
        were already computed at a logging boundary. This helper never
        touches XLA tensors, so enabling perf summaries does not add a
        hidden device sync.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _host_rss_gb() -> float:
    """Return current host resident set size in GB.

    Returns:
        Current process RSS in decimal GB, or ``0.0`` if Linux
        ``/proc`` is unavailable.

    Notes:
        TPU note: HBM is device memory, while RSS is CPU host RAM. RSS
        is not a replacement for the HBM gate, but it gives the
        orchestrator a non-zero memory signal when TPU runtimes cannot
        expose HBM counters.
    """
    try:
        with open("/proc/self/statm", encoding="utf-8") as f:
            resident_pages = int(f.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE") / 1e9
    except (OSError, IndexError, ValueError):
        return 0.0


def _deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            _deep_update(d[k], v)
        else:
            d[k] = v
    return d


def load_config(path: str | None, overrides: dict) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    if path:
        with open(path) as f:
            _deep_update(cfg, yaml.safe_load(f) or {})
    # apply CLI overrides
    for k, v in overrides.items():
        if v is None:
            continue
        if k in cfg and not isinstance(cfg[k], dict):
            cfg[k] = v
            continue
        for section in cfg:
            if k in cfg[section]:
                cfg[section][k] = v
                break
        else:
            cfg.setdefault("_cli", {})[k] = v
    # `train.clip_grad_norm` (the spelling every TPU YAML uses) was a DEAD KEY
    # until 2026-07-10: the clip sites read only `train.max_grad_norm`, whose
    # DEFAULTS value of 1.0 silently won. Harmless while every config meant
    # 1.0 — but the clip-10 probes (probe_clip10/probe_b512c10) actually ran
    # at clip 1.0 because of it. Honor both spellings here, in one place,
    # with `clip_grad_norm` taking precedence when present.
    if "clip_grad_norm" in cfg["train"]:
        cfg["train"]["max_grad_norm"] = float(cfg["train"]["clip_grad_norm"])
    return cfg


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def freeze_depth_internals(model, unfreeze_last_n_blocks: int = 0):
    frozen, kept = 0, 0
    for name, param in model.depth_decoder.named_parameters():
        if any(k in name for k in ("input_projections", "embed_tokens", "lm_heads")):
            param.requires_grad = True
            kept += param.numel()
        else:
            param.requires_grad = False
            frozen += param.numel()
    print(f"Depth decoder: frozen {frozen / 1e6:.0f}M, trainable I/O {kept / 1e6:.0f}M")
    # Phase C3 (opt-in): unfreeze the last N depth transformer blocks for low-LR
    # adaptation to the TR/HI residual distribution. Done at SETUP (before the FSDP
    # wrap), so no risky mid-run param-group surgery. The Phase C2 unmask schedule
    # gates deep-codebook gradients, so these blocks only begin learning once their
    # codebooks unmask -- the "staged" effect without mutating the optimizer mid-run.
    # They land in the `depth_blocks` low-LR group (get_param_groups via is_depth_block).
    if unfreeze_last_n_blocks > 0:
        # Name-based (NOT module-walk): the TPU smoke showed module-walk over
        # `.layers` reported 0M, while this named_parameters() enumeration -- the
        # same one the freeze loop above uses -- correctly sees the 617M of block
        # params. Find the layer count, then unfreeze the last N layer indices.
        idxs = {depth_block_layer_index(name) for name, _ in model.depth_decoder.named_parameters()}
        idxs.discard(None)
        if not idxs:
            print("  [depth-unfreeze] WARNING: no depth transformer-block params found; skipping")
        else:
            n_layers = max(idxs) + 1
            n = min(unfreeze_last_n_blocks, n_layers)
            threshold = n_layers - n  # unfreeze indices [threshold, n_layers)
            uf = 0
            for name, param in model.depth_decoder.named_parameters():
                li = depth_block_layer_index(name)
                if li is not None and li >= threshold:
                    param.requires_grad = True
                    uf += param.numel()
            # Guard: an enabled unfreeze that matched 0 params is a silent no-op
            # (the bug the smoke caught) -- fail loud instead.
            assert uf > 0, (
                f"depth-unfreeze matched 0 params for last {n}/{n_layers} blocks; "
                "check depth-decoder naming (param_classify.depth_block_layer_index)"
            )
            print(
                f"  [depth-unfreeze] unfroze last {n}/{n_layers} depth blocks "
                f"({uf / 1e6:.0f}M) -> low-LR depth_blocks group"
            )


def get_param_groups(model, optim_cfg):
    groups = {
        "lora": {"params": [], "lr": optim_cfg["lr_lora"]},
        "full_ft": {"params": [], "lr": optim_cfg["lr_full_ft"]},
        "projection": {"params": [], "lr": optim_cfg["lr_projection"]},
        "depth": {"params": [], "lr": optim_cfg["lr_depth"]},
        # Phase C3: unfrozen depth-decoder transformer blocks at a LOW LR
        # (default lr_depth x 0.1). Empty -> dropped unless lora.depth_unfreeze_blocks>0.
        "depth_blocks": {
            "params": [],
            "lr": optim_cfg.get("lr_depth_blocks", optim_cfg["lr_depth"] * 0.1),
        },
        "text_embed": {"params": [], "lr": optim_cfg["lr_text_embed"]},
        "model_audio_embed": {
            "params": [],
            "lr": optim_cfg.get("lr_model_audio_embed", optim_cfg["lr_audio_embed"]),
        },
    }
    # Name -> group rules live in param_classify.classify_param (torch-free,
    # shared with the offline checkpoint_group_rms analysis) so live telemetry
    # and post-hoc norm tables can never disagree on membership.
    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue
        groups[classify_param(name)]["params"].append(param)
    result = [g | {"name": n} for n, g in groups.items() if g["params"]]
    print("\n=== Parameter Groups ===")
    for g in result:
        n = sum(p.numel() for p in g["params"])
        print(f"  {g['name']}: {len(g['params'])} tensors, {n / 1e6:.1f}M, lr={g['lr']}")
    return result


def _group_grad_diag(optimizer, device):
    """On-device per-group stability diagnostics for the training dashboard.

    Returns ``(names, values)`` where ``values`` is a 1-D tensor of per-group
    scalars: grad L2 norm, param L2 norm, mean Adam 2nd-moment (``exp_avg_sq``),
    count of non-finite grad elements, and Adam-update L2 norm. Call ONLY at a
    log boundary and BEFORE ``zero_grad`` (grads must be live). Pure XLA ops,
    so the whole bundle materialises in ONE host transfer at log time (no
    per-step sync) -- same discipline as the loss logging. Update-to-weight
    ratio, RMS variants (norm / sqrt(numel); numel is host-static), spike
    ratios and Adam-v drift are derived host-side from these at log time.

    Notes
    -----
    TPU note: this runs AFTER the fused in-place clip and BEFORE
    ``optimizer.step``, so grad norms here are the CLIPPED gradients (what the
    optimizer will actually consume), while ``train/grad_norm`` stays pre-clip.
    ``adam_update_norm`` uses ``exp_avg / (sqrt(exp_avg_sq) + eps)`` from the
    optimizer state, which at this point is one step STALE (moments from the
    previous ``step()``) and skips bias correction — good enough to see
    whether Adam's normalizer absorbs raw grad-norm spikes, not for exact
    bookkeeping of this step's Δθ.
    """
    names: list[str] = []
    vals: list[torch.Tensor] = []
    for pg in optimizer.param_groups:
        gname = pg.get("name")
        if gname is None:
            continue
        gsq = torch.zeros((), device=device)
        psq = torch.zeros((), device=device)
        vsum = torch.zeros((), device=device)
        nonfin = torch.zeros((), device=device)
        usq = torch.zeros((), device=device)
        vcnt = 0
        for p in pg["params"]:
            if not p.requires_grad:
                continue
            g = p.grad if p.grad is not None else torch.zeros_like(p)
            gf = g.float()
            gsq = gsq + (gf * gf).sum()
            nonfin = nonfin + (~torch.isfinite(gf)).sum().to(gsq.dtype)
            pf = p.detach().float()
            psq = psq + (pf * pf).sum()
            st = optimizer.state.get(p)
            if st is not None and "exp_avg_sq" in st:
                vsum = vsum + st["exp_avg_sq"].float().sum()
                vcnt += int(st["exp_avg_sq"].numel())
                if "exp_avg" in st:
                    # Adam's per-element step direction m/(sqrt(v)+eps); the
                    # host multiplies by the group lr to get the update norm.
                    ua = st["exp_avg"].float() / (st["exp_avg_sq"].float().sqrt() + 1e-8)
                    usq = usq + (ua * ua).sum()
        names += [
            f"grad_norm/{gname}",
            f"param_norm/{gname}",
            f"adam_v_mean/{gname}",
            f"nonfinite_grads/{gname}",
            f"adam_update_norm/{gname}",
        ]
        vals += [gsq.sqrt(), psq.sqrt(), vsum / max(vcnt, 1), nonfin, usq.sqrt()]
    if not vals:
        return [], torch.zeros(0, device=device)
    return names, torch.stack(vals)


# ---------------------------------------------------------------------------
# audio demo generation (codebook-0 AR + hierarchical depth)
# ---------------------------------------------------------------------------


@torch.no_grad()
def generate_audio_sample(
    model,
    dataset,
    mimi_encoder,
    device,
    num_codebooks,
    sample_idx=0,
    max_target_frames=80,
    backend=None,
):
    model.eval()
    sample = dataset[sample_idx]
    src_codes_all = sample["audio_codes"]
    src_len = sample["source_length"]
    tgt_len = sample["target_length"]

    src_cb0 = src_codes_all[0, :src_len].unsqueeze(0).to(device)
    generated_cb0 = src_cb0.clone()
    text_ids = torch.full(
        (1, src_len), TinyAyaBackbone.ZERO_PADDING, dtype=torch.long, device=device
    )

    all_generated = []
    for _ in range(max_target_frames):
        mask = torch.ones(1, generated_cb0.shape[1], dtype=torch.long, device=device)
        autocast = (
            backend.autocast_context(dtype=torch.bfloat16)
            if backend
            else torch.amp.autocast("cuda", dtype=torch.bfloat16)
        )
        with autocast:
            backbone_out = model.backbone(
                text_ids=text_ids, audio_codes=generated_cb0, attention_mask=mask
            )
            projected = model.projection(backbone_out["hidden_states"])
            ctx = projected[:, -1:, :]
            ctx_expanded = ctx.expand(1, num_codebooks, -1).contiguous()

            depth_input = torch.zeros(1, num_codebooks, dtype=torch.long, device=device)
            frame = []
            for cb_idx in range(num_codebooks):
                depth_out = model.depth_decoder(
                    input_ids=depth_input,
                    last_hidden_state=ctx_expanded,
                    use_cache=False,
                    return_dict=True,
                )
                tok = depth_out.logits[0, cb_idx, :].argmax(dim=-1)
                frame.append(tok.cpu())
                if cb_idx + 1 < num_codebooks:
                    depth_input[0, cb_idx + 1] = tok
        next_tokens = torch.stack(frame)
        all_generated.append(next_tokens)
        next_cb0 = next_tokens[0].unsqueeze(0).unsqueeze(0).to(device)
        generated_cb0 = torch.cat([generated_cb0, next_cb0], dim=1)
        text_pad = torch.full((1, 1), TinyAyaBackbone.ZERO_PADDING, dtype=torch.long, device=device)
        text_ids = torch.cat([text_ids, text_pad], dim=1)

    gen_codes = torch.stack(all_generated, dim=1)  # [CB, T]
    gt_cb0 = src_codes_all[0, src_len : src_len + gen_codes.shape[1]]
    cb0_acc = (gen_codes[0] == gt_cb0).float().mean().item() if len(gt_cb0) > 0 else 0.0

    src_full = src_codes_all[:, :src_len]
    tgt_full = src_codes_all[:, src_len : src_len + tgt_len]
    model.train()
    return {
        "source_wav": mimi_encoder.decode(src_full).numpy(),
        "target_gt_wav": mimi_encoder.decode(tgt_full).numpy(),
        "generated_wav": mimi_encoder.decode(gen_codes).numpy(),
        "cb0_accuracy": cb0_acc,
    }


# ---------------------------------------------------------------------------
# validation loop
# ---------------------------------------------------------------------------


@torch.no_grad()
def run_validation(
    model,
    val_loader,
    device,
    num_codebooks,
    depth_chunk_size,
    loss_cfg,
    *,
    is_ddp=False,
    backend=None,
    max_batches=None,
    val_debug=False,
) -> dict:
    # @torch.no_grad() (above): val needs no gradients; this was already in
    # place, so the autograd-tape graph theory is NOT the residual cause.
    # The genuinely new lever for the inline-TPU-val NaN is the launcher's
    # XLA_NO_SPECIAL_SCALARS=1 (disables XLA's assume-no-NaN/Inf rewrites).
    model.eval()
    # Audit item #1: TPU-safe validation. All reductions stay as on-device
    # accumulator tensors (no per-batch .item()/.any()/boolean-indexing),
    # so XLA neither stalls on host syncs nor recompiles on dynamic shapes.
    # Materialised exactly once at the end. ``max_batches`` caps the pass.
    is_tpu = "xla" in str(device)
    if is_tpu:
        import torch_xla
    acc_loss = torch.zeros((), device=device)
    acc_text = torch.zeros((), device=device)
    acc_audio = torch.zeros((), device=device)
    per_cb_sum = torch.zeros(num_codebooks, device=device)
    cb0_correct = torch.zeros((), device=device)
    cb0_total = torch.zeros((), device=device)
    # Per-codebook top-1 accuracy accumulator (audio-codebook health, metric #6).
    cb_correct = torch.zeros(num_codebooks, device=device)
    # Text-stream teacher-forced accuracy (text+audio selection gate): counted
    # only on REAL text tokens (id < TEXT_PADDING=262144 -- excludes the 4
    # frame-padding specials, which dominate positions and would inflate acc).
    text_correct = torch.zeros((), device=device)
    text_total = torch.zeros((), device=device)
    n_finite = torch.zeros((), device=device)
    n = 0
    for batch in val_loader:
        if max_batches is not None and n >= max_batches:
            break
        # Multi-host TPU: mirror the train path -- each host feeds its own
        # DistributedSampler shard, shard_to_device assembles the global val
        # batch across hosts (else val collapses to one host's rows too).
        _mh = (
            is_tpu
            and backend is not None
            and hasattr(backend, "shard_to_device")
            and int(getattr(backend, "host_count", lambda: 1)()) > 1
        )
        if _mh:
            text_ids = backend.shard_to_device(batch["text_ids"], ("fsdp", None))
            all_codes = backend.shard_to_device(batch["audio_codes"], ("fsdp", None, None))
            cb0 = all_codes[:, 0, :]
            mask = backend.shard_to_device(batch["attention_mask"], ("fsdp", None))
            loss_mask = backend.shard_to_device(batch["loss_mask"], ("fsdp", None))
            if "user_audio_codes" in batch:
                user_cb0 = backend.shard_to_device(batch["user_audio_codes"][:, 0, :], ("fsdp", None))
                model_cb0 = backend.shard_to_device(batch["model_audio_codes"][:, 0, :], ("fsdp", None))
                full_model_codes = backend.shard_to_device(batch["model_audio_codes"], ("fsdp", None, None))
            else:
                user_cb0 = cb0
                model_cb0 = None
                full_model_codes = None
        else:
            text_ids = batch["text_ids"].to(device)
            all_codes = batch["audio_codes"].to(device)
            cb0 = all_codes[:, 0, :]
            mask = batch["attention_mask"].to(device)
            loss_mask = batch["loss_mask"].to(device)

            # Mark input sharding for TPU SPMD -- the training forward does this
            # (mark_sharding at the macro-step); without it under FSDPv2 the
            # partitioner mishandles the val inputs against the sharded params
            # and the forward goes non-finite (CPU eager forward is finite).
            if is_tpu and backend is not None and hasattr(backend, "mark_sharding"):
                backend.mark_sharding(text_ids, ("fsdp", None))
                backend.mark_sharding(all_codes, ("fsdp", None, None))
                backend.mark_sharding(mask, ("fsdp", None))
                backend.mark_sharding(loss_mask, ("fsdp", None))

            # Parallel streams (Moshi-style)
            if "user_audio_codes" in batch:
                user_cb0 = batch["user_audio_codes"][:, 0, :].to(device)
                model_cb0 = batch["model_audio_codes"][:, 0, :].to(device)
                full_model_codes = batch["model_audio_codes"].to(device)
            else:
                user_cb0 = cb0
                model_cb0 = None
                full_model_codes = None

        autocast = (
            backend.autocast_context(dtype=torch.bfloat16)
            if backend
            else torch.amp.autocast("cuda", dtype=torch.bfloat16)
        )
        with autocast:
            output = model(
                text_ids=text_ids,
                audio_codes=user_cb0 if model_cb0 is not None else cb0,
                model_audio_codes=model_cb0,
                attention_mask=mask,
                full_audio_codes=full_model_codes[:, :num_codebooks, :]
                if full_model_codes is not None
                else all_codes[:, :num_codebooks, :],
                depth_chunk_size=depth_chunk_size,
            )
            text_logits, audio_logits, hidden = output[0], output[1], output[2]
            audio_targets = (
                full_model_codes[:, :num_codebooks, :]
                if full_model_codes is not None
                else all_codes[:, :num_codebooks, :]
            )
            losses = compute_hierarchical_translation_loss(
                text_logits,
                audio_logits,
                text_ids,
                audio_targets,
                mask,
                loss_mask,
                text_weight=loss_cfg["text_weight"],
                audio_weight=loss_cfg["audio_weight"],
                text_padding_weight=loss_cfg.get("text_padding_weight", 0.01),
                zero_padding_weight=loss_cfg.get("zero_padding_weight", 0.0),
                # val stays CLEAN CE (no label smoothing) for a true
                # generalization metric; smoothing is applied on the train call.
            )
            # First-batch NaN localization (one host sync; diagnostic only).
            # Pinpoints whether the non-finite originates in the backbone
            # (hidden -> attention/mask), the heads (logits), or the loss.
            # IMPORTANT: a pre-sync ``isfinite().all()`` is an UNRELIABLE probe
            # on XLA -- it can read a different materialization than the
            # accumulator's later host transfer (pytorch/xla#1665, #2516), which
            # is exactly what misled the previous debug session. Force the
            # forward+loss to actually execute (mark_step) and read on host
            # via .item() so this line reflects the same value the accumulator
            # will see.
            if n == 0 and val_debug:
                if is_tpu:
                    torch_xla.sync()
                fin = lambda t: bool(torch.isfinite(t).all().item())
                print(
                    "  [val-debug] finite: "
                    f"hidden={fin(hidden)} "
                    f"text_logits={fin(text_logits)} "
                    f"audio_logits={fin(audio_logits)} "
                    f"loss={fin(losses['loss'])}",
                    flush=True,
                )
        # Finite-guarded accumulation: a degenerate val batch (e.g. all-pad,
        # loss_mask.sum()==0) makes the loss-fn normalisation divide by zero
        # -> NaN, which would poison the whole pass. Skip such batches via a
        # device-side mask (no host sync) and divide by the finite count.
        bl = losses["loss"].detach()
        finite = torch.isfinite(bl)
        zero = torch.zeros_like(bl)
        acc_loss = acc_loss + torch.where(finite, bl, zero)
        acc_text = acc_text + torch.where(finite, losses["text_loss"].detach(), zero)
        acc_audio = acc_audio + torch.where(finite, losses["audio_loss"].detach(), zero)
        pcb = losses["per_codebook_loss"].detach()
        per_cb_sum = per_cb_sum + torch.where(finite, pcb, torch.zeros_like(pcb))
        n_finite = n_finite + finite.to(acc_loss.dtype)

        # cb0 teacher-forced acc on target positions (shifted next-token).
        # Static-shape masked reduction -- NO boolean indexing (which
        # would produce a dynamic-length tensor and recompile on XLA).
        # TARGET = audio_targets (the DELAYED model_audio_codes the model
        # predicts and the loss trains against), NOT all_codes (batch
        # "audio_codes", which is UNDELAYED). Using all_codes was a real bug:
        # CB0 has codebook-delay 0 so all_codes[0] == audio_targets[0] and its
        # accuracy was correct, but CB1-7 are delayed by 1..7 frames, so the
        # metric compared the model's (correctly-delayed) predictions against
        # the undelayed target -> off-by-k misalignment -> CB1-7 accuracy
        # pinned at ~random even when fully learned (verified on the overfit
        # run: CB1-7 loss -> ~0.05 while this metric read ~0%). audio_targets
        # is defined above (= full_model_codes, delayed) so loss and accuracy
        # now use the SAME target.
        pred = audio_logits[:, 0, :-1].argmax(dim=-1)  # [B, T-1]
        target = audio_targets[:, 0, 1:]
        m = (loss_mask[:, 1:].bool() & mask[:, 1:].bool()).to(acc_loss.dtype)
        cb0_correct = cb0_correct + ((pred == target).to(m.dtype) * m).sum()
        cb0_total = cb0_total + m.sum()
        # All-codebook top-1 acc (same target positions; static-shape, no
        # boolean indexing). [B,CB,T-1] preds vs targets, masked, summed -> [CB].
        preds_cb = audio_logits[:, :, :-1].argmax(dim=-1)  # [B, CB, T-1]
        tgts_cb = audio_targets[:, :num_codebooks, 1:]
        cb_correct = cb_correct + ((preds_cb == tgts_cb).to(m.dtype) * m.unsqueeze(1)).sum(
            dim=(0, 2)
        )
        # Text teacher-forced next-token acc (same shift convention as the
        # text loss). Static-shape masked reduction like cb0 above. Mask =
        # target span AND real text tokens only: the interleaver fills most
        # frames with padding specials (TEXT/END_OF_TEXT/ZERO/IN_WORD, ids >=
        # 262144), and counting those would report ~100% acc on a stream
        # that never learned a single real word.
        text_pred = text_logits[:, :-1].argmax(dim=-1)  # [B, T-1]
        text_tgt = text_ids[:, 1:]
        m_txt = m * (text_tgt < 262144).to(m.dtype)
        text_correct = text_correct + ((text_pred == text_tgt).to(m.dtype) * m_txt).sum()
        text_total = text_total + m_txt.sum()
        n += 1
        if is_tpu:
            torch_xla.sync()

    if n == 0:
        model.train()
        return {}

    # Multi-host DDP all-reduce so every rank sees identical metrics.
    # No-op under single-host v6e-8 SPMD (world_size == 1; the 8 chips are
    # reduced transparently by the partitioner).
    if backend and backend.world_size() > 1:
        ws = backend.world_size()
        acc_loss = backend.reduce_mean(acc_loss) * ws
        acc_text = backend.reduce_mean(acc_text) * ws
        acc_audio = backend.reduce_mean(acc_audio) * ws
        per_cb_sum = backend.reduce_mean(per_cb_sum) * ws
        cb0_correct = backend.reduce_mean(cb0_correct) * ws
        cb0_total = backend.reduce_mean(cb0_total) * ws
        cb_correct = backend.reduce_mean(cb_correct) * ws
        text_correct = backend.reduce_mean(text_correct) * ws
        text_total = backend.reduce_mean(text_total) * ws
        n_finite = backend.reduce_mean(n_finite) * ws

    # Single host-sync point for the whole validation pass.
    cc = float(cb0_correct.item())
    ct = float(cb0_total.item())
    nf = float(n_finite.item())
    model.train()
    if nf == 0:
        print(f"  [val] WARNING: all {n} val batches produced non-finite loss", flush=True)
        return {}
    if nf < n:
        print(f"  [val] skipped {n - int(nf)}/{n} non-finite val batches", flush=True)
    inv = 1.0 / nf
    _vt = (acc_text * inv).item()
    _va = (acc_audio * inv).item()
    return {
        "val/loss": (acc_loss * inv).item(),
        "val/text_loss": _vt,
        "val/audio_loss": _va,
        # Phase D: composite of the RAW stream losses (audio-heavier) — the metric
        # for best_by_val + early stopping, so neither stream can be sacrificed.
        "val/composite": composite_val_loss(
            _vt,
            _va,
            float(loss_cfg.get("composite_text_w", 0.4)),
            float(loss_cfg.get("composite_audio_w", 0.6)),
        ),
        "val/cb0_acc": (cc / ct) if ct > 0 else 0.0,
        # Real-token text acc; 0.0 with tt==0 means "no real text tokens seen"
        # (audio-only data), distinct from "text stream stuck at random".
        "val/text_acc": (
            (float(text_correct.item()) / float(text_total.item()))
            if float(text_total.item()) > 0
            else 0.0
        ),
        "val/per_codebook_loss": (per_cb_sum * inv).detach().cpu().tolist(),
        "val/per_codebook_acc": (
            (cb_correct / ct).detach().cpu().tolist() if ct > 0 else [0.0] * num_codebooks
        ),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--dataset_mode", choices=["memory", "streaming"], default="streaming")

    # memory-mode data dir (back-compat for 50-pair smoke)
    p.add_argument("--data_dir", type=str, default=None)

    # streaming-mode splits (override)
    p.add_argument("--train_split", type=str, default=None)
    p.add_argument("--val_split", type=str, default=None)
    p.add_argument("--encoded_dir", type=str, default=None)

    # overridable training knobs
    p.add_argument("--max_steps", type=int, default=None)
    p.add_argument("--batch_size", type=int, default=None)
    p.add_argument("--grad_accum", type=int, default=None)
    p.add_argument("--max_frames", type=int, default=None)
    p.add_argument("--depth_chunk_size", type=int, default=None)
    p.add_argument("--num_codebooks", type=int, default=None)
    p.add_argument("--warmup_steps", type=int, default=None)
    p.add_argument("--compile_warmup_steps", type=int, default=None)
    p.add_argument("--num_workers", type=int, default=None)

    # logging
    p.add_argument("--log_every", type=int, default=None)
    p.add_argument("--save_every", type=int, default=None)
    p.add_argument("--audio_every", type=int, default=None)
    p.add_argument("--val_every", type=int, default=None)
    p.add_argument("--save_dir", type=str, default=None)
    p.add_argument("--wandb_project", type=str, default=None)
    p.add_argument("--wandb_run_name", type=str, default=None)
    p.add_argument("--use_wandb", type=lambda s: s.lower() in ("1", "true", "yes"), default=None)

    p.add_argument("--push_to_hub", type=lambda s: s.lower() in ("1", "true", "yes"), default=None)
    p.add_argument("--hub_repo_id", type=str, default=None)

    p.add_argument("--backend", type=str, default=None, choices=["auto", "gpu", "tpu"])
    p.add_argument("--resume", type=str, default=None, help="checkpoint dir to resume from")

    # --- W&B sweep knobs (passed as CLI args by `wandb agent` via ${args}) ---
    # Generic ones (lr_lora/lr_depth -> optim, text_weight -> loss,
    # weight_decay -> train, val_on_tpu -> logging) map through load_config by
    # name; lora_r/lora_alpha_mult need the explicit r/alpha handling in main().
    p.add_argument(
        "--sweep", action="store_true", help="W&B sweep run: log sweep/text_ok health flag"
    )
    p.add_argument("--lr_lora", type=float, default=None)
    p.add_argument("--lr_depth", type=float, default=None)
    p.add_argument("--text_weight", type=float, default=None)
    p.add_argument("--weight_decay", type=float, default=None)
    p.add_argument("--val_on_tpu", type=lambda s: s.lower() in ("1", "true", "yes"), default=None)
    p.add_argument("--lora_r", type=int, default=None)
    p.add_argument(
        "--lora_alpha_mult", type=int, default=None, help="lora.alpha = lora_alpha_mult * lora_r"
    )
    p.add_argument(
        "--lora_dropout", type=float, default=None, help="lora.dropout (Phase E sweep knob)"
    )
    # Capacity-sweep knobs (scale phase): structural axes for the v0.3-scale sweep.
    p.add_argument(
        "--lora_exclude_top",
        type=int,
        default=None,
        help="lora.lora_exclude_top (# top layers left frozen; sweep knob)",
    )
    p.add_argument(
        "--use_rslora",
        type=lambda s: s.lower() in ("1", "true", "yes"),
        default=None,
        help="lora.use_rslora (alpha/sqrt(r) rank-stable scaling)",
    )
    p.add_argument(
        "--target_modules",
        type=str,
        default=None,
        help="lora.target_modules as a JSON list or comma/space-separated "
        'string (W&B sweep categorical, e.g. \'["q_proj","v_proj"]\')',
    )
    # Depth-path capacity knobs (v0.3 reval arm F). Unlike lora_r/alpha these need
    # no explicit mapping: the names match cfg["lora"].depth_unfreeze_blocks and
    # cfg["optim"].lr_depth_blocks, so load_config's section-matcher routes them.
    p.add_argument(
        "--depth_unfreeze_blocks",
        type=int,
        default=None,
        help="lora.depth_unfreeze_blocks: unfreeze last N Moshi depth "
        "blocks (adds CB1-7 capacity; watch HBM). 0 = frozen (default).",
    )
    p.add_argument(
        "--lr_depth_blocks",
        type=float,
        default=None,
        help="optim.lr_depth_blocks: low LR for the unfrozen depth blocks "
        "(only used when depth_unfreeze_blocks > 0).",
    )
    return p


def _parse_target_modules(raw):
    """Parse a --target_modules sweep value into a list of module-name strings.

    W&B serializes a list categorical as a JSON string ('["q_proj","v_proj"]') or
    it can arrive comma/space-separated; accept all forms. A single bare name
    returns a one-element list.
    """
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    s = str(raw).strip()
    try:
        val = json.loads(s)
        if isinstance(val, list):
            return [str(x) for x in val]
    except (ValueError, TypeError):
        pass
    cleaned = s.strip("[]").replace('"', "").replace("'", "").replace(",", " ")
    return [tok for tok in cleaned.split() if tok]


def main():
    args = build_parser().parse_args()
    overrides = {
        k: v
        for k, v in vars(args).items()
        # lora_r/lora_alpha_mult map to lora.r/lora.alpha (name mismatch) and
        # `sweep` is a control flag -- all handled explicitly below. The capacity
        # knobs (lora_exclude_top/use_rslora/target_modules) also map under `lora`.
        if k
        not in (
            "config",
            "dataset_mode",
            "data_dir",
            "resume",
            "sweep",
            "lora_r",
            "lora_alpha_mult",
            "lora_dropout",
            "lora_exclude_top",
            "use_rslora",
            "target_modules",
        )
    }
    cfg = load_config(args.config, overrides)

    # W&B sweep: LoRA rank/alpha (alpha = mult * r) need explicit mapping onto
    # the nested `lora` section. Everything else (lr_lora/lr_depth/text_weight/
    # weight_decay/warmup_steps/max_steps/val_every/val_on_tpu) flowed through
    # load_config above by matching the cfg section key.
    if args.lora_r is not None:
        cfg.setdefault("lora", {})["r"] = args.lora_r
    if args.lora_alpha_mult is not None:
        _r = cfg.get("lora", {}).get("r", 16)
        cfg.setdefault("lora", {})["alpha"] = args.lora_alpha_mult * _r
    if args.lora_dropout is not None:
        cfg.setdefault("lora", {})["dropout"] = args.lora_dropout
    # Capacity-sweep structural knobs (scale phase).
    if args.lora_exclude_top is not None:
        cfg.setdefault("lora", {})["lora_exclude_top"] = args.lora_exclude_top
    if args.use_rslora is not None:
        cfg.setdefault("lora", {})["use_rslora"] = args.use_rslora
    if args.target_modules is not None:
        cfg.setdefault("lora", {})["target_modules"] = _parse_target_modules(args.target_modules)
    if args.sweep:
        print(
            f"[sweep] overrides -> lr_lora={cfg['optim'].get('lr_lora')} "
            f"lr_depth={cfg['optim'].get('lr_depth')} "
            f"lora={cfg.get('lora')} text_weight={cfg['loss'].get('text_weight')} "
            f"warmup={cfg['train'].get('warmup_steps')} "
            f"wd={cfg['train'].get('weight_decay')} max_steps={cfg['train'].get('max_steps')}",
            flush=True,
        )

    # ---- distributed init (GPU or TPU)
    backend_type = cfg.get("backend", "auto")
    if backend_type == "auto":
        backend_type = None  # auto-detect
    backend = get_backend(backend_type)
    backend.init_distributed()
    device = backend.get_device()
    is_main = backend.is_main_process()

    # iter 18 lever 4: start the XLA profiler server so external tools
    # (capture_profile.py / TensorBoard) can attach. Rank-0 only --
    # multi-host pods would collide on port 9012. Single-host v6e-8
    # has one process so this is unconditional once is_main passes.
    is_tpu_early = cfg.get("backend", "auto") == "tpu"
    # Multi-host TPU (v6e-16 = 4 hosts): switches on the minibatch
    # data-parallel input pipeline (DistributedSampler per host +
    # backend.shard_to_device). host_count() == 1 on v6e-8 -> single-host
    # path unchanged. Verified live on a 4-host mesh (spmd_minibatch_truth.py:
    # per-host (8,4) -> global (32,4), all 4 hosts' distinct rows assembled).
    n_hosts = int(getattr(backend, "host_count", lambda: 1)())
    multihost = is_tpu_early and n_hosts > 1
    # iter 20 fix: the return value of xp.start_server() must be
    # bound to a long-lived name. Per torch_xla.debug.profiler
    # docstring: "If this object is garbage collected, the profiler
    # server is shut down." Iter 17-19 dropped the return value, so
    # the gRPC server died immediately after the print statement and
    # the external xp.trace() always got "Connection refused". Stash
    # it on `main` itself so it survives until interpreter exit.
    main._xp_profiler_server = None
    if is_tpu_early and is_main:
        try:
            import torch_xla.debug.profiler as xp

            xp_port = int(os.environ.get("XLA_PROFILER_PORT", "9012"))
            main._xp_profiler_server = xp.start_server(xp_port)
            print(
                f"[profiler] xp.start_server listening on :{xp_port}"
                f" (server obj retained: {main._xp_profiler_server!r})",
                flush=True,
            )
        except Exception as e:
            print(f"[profiler] xp.start_server failed: {e}", flush=True)

    # Per-host RNG offset. Under PJRT SPMD, LOCAL_RANK is unset (it's a
    # GPU/torchrun var), so every host shared one seed -- fine for weights
    # (must match across hosts) but the DistributedSampler needs distinct
    # per-host shuffling, which it gets from its own rank, not this seed.
    torch.manual_seed(int(cfg["train"].get("seed", 42)) + int(os.environ.get("LOCAL_RANK", 0)))

    # Resolve per_chip_batch -> PER-HOST loader batch ONCE, before any consumer
    # (collator batch_pad_to, DataLoader, static-shape asserts) -- they all read
    # cfg["train"]["batch_size"] (the per-host CPU batch). The GLOBAL batch is
    # per-host x host_count, assembled on-device by the minibatch pipeline; the
    # banner (effective_batch) reports it.
    if cfg["train"].get("per_chip_batch"):
        if cfg.get("backend", "auto") != "tpu":
            raise ValueError("train.per_chip_batch is TPU-SPMD-only; set batch_size on GPU")
        cfg["train"]["batch_size"] = resolve_loader_batch(
            cfg["train"], backend.world_size(), n_hosts
        )
        if is_main:
            _gb = cfg["train"]["batch_size"] * n_hosts
            print(
                f"[batch] per_chip_batch={cfg['train']['per_chip_batch']} -> "
                f"per_host loader batch {cfg['train']['batch_size']} x {n_hosts} hosts "
                f"= global {_gb} (before grad_accum)",
                flush=True,
            )

    # Decouple the VAL loader batch from the (locked) train batch. Val is
    # inference-only: a larger per-chip val batch only shortens the every-
    # `val_every` val cycle (fewer, bigger sharded batches; shard_to_device
    # is shape-agnostic) -- it cannot change optimizer math. TPU-SPMD-only,
    # same resolve path as train. Unset => val batch == train batch.
    val_batch_size = cfg["train"]["batch_size"]
    if cfg["logging"].get("val_per_chip_batch"):
        if cfg.get("backend", "auto") != "tpu":
            raise ValueError("logging.val_per_chip_batch is TPU-SPMD-only")
        val_batch_size = resolve_loader_batch(
            {**cfg["train"], "per_chip_batch": cfg["logging"]["val_per_chip_batch"]},
            backend.world_size(),
            n_hosts,
        )
        if is_main:
            print(
                f"[batch] val_per_chip_batch={cfg['logging']['val_per_chip_batch']} -> "
                f"per_host val loader batch {val_batch_size} x {n_hosts} hosts "
                f"= global {val_batch_size * n_hosts}",
                flush=True,
            )

    if is_main:
        print("\n=== Effective config ===")
        print(json.dumps(cfg, indent=2, default=str))

    num_codebooks = cfg["train"]["num_codebooks"]
    depth_chunk = cfg["train"]["depth_chunk_size"]
    max_frames = cfg["data"]["max_frames"]

    # ---- model
    if is_main:
        print("\n=== Building composite model ===")
    use_scan = bool(cfg["train"].get("use_scan_layers", False))
    use_xla_ckpt = bool(cfg["train"].get("xla_grad_checkpoint", False))
    model = TinyAyaMoshiComposite(
        num_codebooks=num_codebooks,
        use_scan_layers=use_scan,
        xla_grad_checkpoint=use_xla_ckpt,
    )
    _lora_cfg = cfg.get("lora", {})
    model.backbone = apply_lora(
        model.backbone,
        r=_lora_cfg.get("r", 16),
        lora_alpha=_lora_cfg.get("alpha", 32),
        target_modules=_lora_cfg.get("target_modules", ["q_proj", "v_proj", "embed_tokens"]),
        num_full_ft_layers=_lora_cfg.get("num_full_ft_layers", 0),
        lora_exclude_top=_lora_cfg.get("lora_exclude_top", 2),
        lora_dropout=_lora_cfg.get("dropout", 0.0),
        use_rslora=bool(_lora_cfg.get("use_rslora", False)),
        # scan_layers stacks per-layer param pytrees and requires identical
        # keys on every layer; under scan, exclude_top is realised by
        # FREEZING the top adapters instead of not creating them.
        scan_homogeneous=use_scan,
    )
    freeze_depth_internals(
        model, unfreeze_last_n_blocks=int(_lora_cfg.get("depth_unfreeze_blocks", 0))
    )
    for p in model.projection.parameters():
        p.requires_grad = True

    # Resume: load model weights BEFORE FSDP wrapping.
    # FSDP shards params during wrap_model(), so loading into an already-sharded
    # model is broken. We load weights into the unwrapped model, then FSDP wraps
    # the correctly-initialized params. Optimizer state is NOT restored (Adam
    # momentum restarts) but model weights are correct.
    from src.training.checkpointing import (
        fetch_checkpoint_file,
        find_latest_checkpoint,
        load_checkpoint,
        read_checkpoint_metadata,
    )

    start_step = 0
    resume_wandb_run_id = None
    resume_meta: dict = {}
    resume_dir = args.resume
    if resume_dir == "auto":
        resume_dir = find_latest_checkpoint(cfg["logging"]["save_dir"])
    if resume_dir:
        start_step = load_checkpoint(model, None, None, resume_dir)
        # Recover the original W&B run id so a preempted run continues the SAME
        # dashboard run on restart instead of fragmenting into a new run. The
        # same metadata carries best_val / patience_left (restored at loop
        # setup) so a resume cannot overwrite best_by_val with a worse ckpt.
        resume_meta = read_checkpoint_metadata(resume_dir)
        resume_wandb_run_id = resume_meta.get("wandb_run_id")
        # Host RNG restore (best-effort): keeps the dropout stream and any
        # host-side shuffle RNG from replaying the fresh-start sequence.
        rng_p = fetch_checkpoint_file(resume_dir, "rng.pt") if start_step > 0 else None
        if rng_p is not None:
            try:
                _rng = torch.load(rng_p, map_location="cpu", weights_only=True)
                torch.set_rng_state(_rng["torch"])
                if cfg.get("backend", "auto") == "tpu" and "xla" in _rng:
                    import torch_xla.core.xla_model as _xm  # noqa: PLC0415

                    _xm.set_rng_state(int(_rng["xla"]))
                if is_main:
                    print(f"Restored host RNG state from {resume_dir}")
            except Exception as e:  # noqa: BLE001 - best-effort, never blocks resume
                if is_main:
                    print(f"[resume] WARNING: rng restore failed ({e}); continuing")
        if is_main:
            _msg = f"Loaded model weights from {resume_dir} (step {start_step})"
            if resume_wandb_run_id:
                _msg += f"; will resume W&B run {resume_wandb_run_id}"
            print(_msg)

    model = model.to(device)

    # Gradient checkpointing strategy:
    #   * GPU: enable HF's per-layer grad checkpoint here, before DDP
    #     wrapping. This is the standard HF Trainer pattern.
    #   * TPU: do NOT call HF's gradient_checkpointing_enable -- in
    #     torch_xla 2.9 it raises from torch._get_device_module("xla").
    #     We use the ``xla_grad_checkpoint`` flag instead, which routes
    #     through scan_utils.
    if cfg.get("backend", "auto") != "tpu":
        model.backbone.gradient_checkpointing_enable()
    model = backend.wrap_model(model)
    # iter 24e: barrier helper DISABLED. Bisection evidence:
    #   iter 24d (barrier ON, lever 6 OFF, b=16) -> NaN at step 3
    #   iter 24c (barrier ON, lever 6 ON,  b=16) -> NaN at step 32
    #   iter 23  (barrier OFF, lever 6 OFF, b=16) -> NaN-free 257 steps,
    #                                                OOM at step 258
    # The barrier helper is the proven NaN trigger -- the 42
    # register_full_backward_hook calls force XLA to materialize 42
    # backward-graph boundaries that don't fuse, exposing per-layer
    # bf16 underflow on v6e (pytorch/xla #8591). Lever 6 (fp32 norm
    # reduction) was MASKING the NaN, not causing it.
    # We accept the iter 23 OOM at step 258 here; mitigation in 24f
    # via batch_size=8 (per #8591 explicit upstream advice) or via
    # checkpoint-and-resume.
    barrier_enabled = bool(cfg.get("train", {}).get("fsdp_barrier_hook", False))
    if cfg.get("backend", "auto") == "tpu" and barrier_enabled:
        _apply_fsdpv2_backward_barriers(model)
    if hasattr(backend, "diagnose"):
        backend.diagnose("post-wrap")
    unwrapped = (
        model._fsdp_wrapped_module
        if hasattr(model, "_fsdp_wrapped_module")
        else (model.module if hasattr(model, "module") else model)
    )
    fsdp_model = model  # keep reference to FSDP wrapper for save_checkpoint

    total = sum(p.numel() for p in unwrapped.parameters())
    trainable = sum(p.numel() for p in unwrapped.parameters() if p.requires_grad)
    if is_main:
        print(
            f"Total {total / 1e9:.2f}B, trainable {trainable / 1e6:.0f}M "
            f"({100 * trainable / total:.1f}%)"
        )

    # ---- data
    if is_main:
        print("\n=== Datasets ===")
    # On TPU we MUST pad batches to a bounded static shape set, otherwise
    # XLA recompiles per unique sequence length seen (pytorch/xla #4203 /
    # https://docs.pytorch.org/xla/master/perf/recompilation.html). On
    # GPU/CPU dynamic shapes are fine, so we only force static padding
    # when the backend is TPU.
    is_tpu_cfg = cfg.get("backend", "auto") == "tpu"
    bucket_frames = None
    if is_tpu_cfg and cfg["data"].get("bucket_frames"):
        bucket_frames = normalize_buckets(
            cfg["data"]["bucket_frames"],
            max_frames=max_frames,
        )
    pad_to = bucket_frames or (cfg["data"].get("max_frames") if is_tpu_cfg else None)
    # iter 24h: also pad the batch axis on TPU. `drop_last=True` alone
    # left 1035 micro-batches at b=8, so step 259 crossed the epoch
    # boundary inside a 4-way grad-accum graph. Padded tails keep the
    # shape static and avoid throwing away real examples.
    batch_pad_to = cfg["train"]["batch_size"] if is_tpu_cfg else None
    expected_codebooks = num_codebooks if is_tpu_cfg else None
    collator = InterleavedCollator(
        pad_to=pad_to,
        batch_pad_to=batch_pad_to,
        expected_num_codebooks=expected_codebooks,
    )
    # Phase E: a SEPARATE train collator carries SpecAugment (input-stream masking);
    # the shared `collator` above stays clean for validation. No-op when disabled.
    _sa_cfg = cfg.get("spec_augment")
    train_collator = (
        InterleavedCollator(
            pad_to=pad_to,
            batch_pad_to=batch_pad_to,
            expected_num_codebooks=expected_codebooks,
            spec_augment=_sa_cfg,
        )
        if (_sa_cfg and _sa_cfg.get("enabled"))
        else collator
    )
    if _sa_cfg and _sa_cfg.get("enabled") and is_main:
        print(f"  [spec-augment] ON (train only): {_sa_cfg}", flush=True)
    # Val collator must pad the batch axis to the VAL loader batch (the
    # collator raises when real_b > batch_pad_to). Only distinct when
    # logging.val_per_chip_batch decouples the val batch from train.
    val_collator = collator
    if is_tpu_cfg and val_batch_size != cfg["train"]["batch_size"]:
        val_collator = InterleavedCollator(
            pad_to=pad_to,
            batch_pad_to=val_batch_size,
            expected_num_codebooks=expected_codebooks,
        )
    if args.dataset_mode == "streaming":
        if not cfg["data"]["train_split"]:
            raise ValueError("train_split required in streaming mode")
        # Text supervision active => alignment resolution failures must be
        # fatal, not a silent all-ZERO_PADDING text stream (the v0.3
        # "audio-only" misdiagnosis).
        _require_align = float(cfg["loss"].get("text_weight", 0.0)) > 0.0
        train_ds = StreamingTranslationDataset(
            cfg["data"]["train_split"],
            unwrapped.backbone.tokenizer,
            max_frames=max_frames,
            audio_frame_rate=cfg["data"]["audio_frame_rate"],
            encoded_dir=cfg["data"]["encoded_dir"],
            require_alignments=_require_align,
        )
        val_ds = None
        if cfg["data"]["val_split"] and Path(cfg["data"]["val_split"]).exists():
            val_ds = StreamingTranslationDataset(
                cfg["data"]["val_split"],
                unwrapped.backbone.tokenizer,
                max_frames=max_frames,
                audio_frame_rate=cfg["data"]["audio_frame_rate"],
                encoded_dir=cfg["data"]["encoded_dir"],
                require_alignments=_require_align,
            )
    else:
        train_ds = TranslationDataset(
            args.data_dir, unwrapped.backbone.tokenizer, max_frames=max_frames
        )
        val_ds = None

    num_workers = cfg["data"]["num_workers"]
    is_tpu = cfg.get("backend", "auto") == "tpu"
    if backend.world_size() > 1 and not is_tpu:
        num_workers = min(num_workers, 6)

    # TPU note: by this point `wrap_model` has moved the model onto the
    # XLA device, which fully initializes the TPU runtime (libtpu) in
    # THIS process -- including libtpu's own tcmalloc and background
    # threads. DataLoader's default `fork` start method would clone that
    # half-initialized allocator into every worker; the first alloc/free
    # in the child then corrupts the heap ("tcmalloc: Attempt to free
    # invalid pointer" -> SIGABRT in the worker, surfaced to the parent
    # at the next mark_step). Use `spawn` so workers get a clean
    # interpreter that never inherits libtpu state. GPU keeps the default
    # fork (no libtpu; fork is cheaper). With spawn the per-worker startup
    # cost is real, so keep workers alive across epochs.
    mp_context = "spawn" if (is_tpu and num_workers > 0) else None
    use_persistent = num_workers > 0

    bucket_batch_sampler = None
    if is_tpu and bucket_frames is not None:
        if not isinstance(train_ds, StreamingTranslationDataset):
            raise ValueError("data.bucket_frames currently requires streaming dataset mode")
        if is_main:
            print(
                f"[data] scanning {len(train_ds)} encoded shapes for bucket_frames={bucket_frames}",
                flush=True,
            )
        bucket_lengths = _streaming_effective_frame_lengths(train_ds, max_frames=max_frames)
        bucket_batch_sampler = BucketedMacroBatchSampler(
            bucket_lengths,
            bucket_frames,
            batch_size=cfg["train"]["batch_size"],
            grad_accum=cfg["train"]["grad_accum"],
            seed=int(cfg["train"].get("seed", 42)),
            shuffle=True,
            warmup_first=True,
        )
        if is_main:
            fixed_tokens = len(bucket_lengths) * max_frames
            bucketed_tokens = sum(
                count * bucket for bucket, count in bucket_batch_sampler.bucket_counts.items()
            )
            print(
                "[data] bucket_counts="
                f"{dict(sorted(bucket_batch_sampler.bucket_counts.items()))} "
                f"padded_examples_per_epoch={bucket_batch_sampler.padded_examples_per_epoch} "
                f"token_reduction_vs_fixed={100 * (1 - bucketed_tokens / fixed_tokens):.2f}%",
                flush=True,
            )

    if multihost:
        # Multi-host TPU minibatch DP: each host draws DISTINCT rows (its
        # DistributedSampler shard); backend.shard_to_device then assembles the
        # global batch across hosts (verified live: per-host (8,4) -> global
        # (32,4), all 4 hosts' rows present). drop_last keeps shards even so the
        # cross-host val reduce stays balanced.
        if bucket_batch_sampler is not None:
            raise ValueError(
                "data.bucket_frames + multi-host TPU is unsupported: "
                "BucketedMacroBatchSampler is not host-aware. Use the plain path."
            )
        _rank = backend.process_index()
        train_sampler = DistributedSampler(
            train_ds, num_replicas=n_hosts, rank=_rank, shuffle=True, drop_last=True
        )
        val_sampler = (
            DistributedSampler(
                val_ds, num_replicas=n_hosts, rank=_rank, shuffle=False, drop_last=True
            )
            if val_ds is not None
            else None
        )
    elif is_tpu:
        # Single-host SPMD: one process, no distributed sampler.
        train_sampler = None
        val_sampler = None
    elif backend.world_size() > 1:
        train_sampler = DistributedSampler(train_ds, shuffle=True, drop_last=True)
        val_sampler = DistributedSampler(val_ds, shuffle=False, drop_last=False) if val_ds else None
    else:
        train_sampler = None
        val_sampler = None

    # TPU/XLA needs the batch dimension to stay static. The collator
    # pads the tail batch to `batch_size`, so keep drop_last=False and
    # preserve the full epoch.
    train_drop_last = False
    if bucket_batch_sampler is not None:
        train_sampler = bucket_batch_sampler
        train_loader = torch.utils.data.DataLoader(
            train_ds,
            batch_sampler=bucket_batch_sampler,
            collate_fn=train_collator,
            num_workers=num_workers,
            pin_memory=cfg["data"]["pin_memory"] and not is_tpu,
            persistent_workers=use_persistent,
            multiprocessing_context=mp_context,
        )
    else:
        train_loader = torch.utils.data.DataLoader(
            train_ds,
            batch_size=cfg["train"]["batch_size"],
            shuffle=(train_sampler is None),
            sampler=train_sampler,
            collate_fn=train_collator,
            num_workers=num_workers,
            pin_memory=cfg["data"]["pin_memory"] and not is_tpu,
            persistent_workers=use_persistent,
            multiprocessing_context=mp_context,
            drop_last=train_drop_last,
        )
    if is_main:
        print(
            "[data] "
            f"train_rows={len(train_ds)} train_batches={len(train_loader)} "
            f"drop_last={train_drop_last} pad_to={pad_to} batch_pad_to={batch_pad_to}",
            flush=True,
        )
    val_loader = None
    if val_ds is not None:
        val_loader = torch.utils.data.DataLoader(
            val_ds,
            batch_size=val_batch_size,
            shuffle=False,
            sampler=val_sampler,
            collate_fn=val_collator,
            num_workers=num_workers,
            pin_memory=cfg["data"]["pin_memory"] and not is_tpu,
            persistent_workers=use_persistent,
            multiprocessing_context=mp_context,
        )

    # ---- mimi decoder for demos
    if is_main:
        print("\n=== Loading Mimi for audio monitoring ===")
    from src.data.mimi_encoder import MimiEncoder

    mimi_device = "cpu" if is_tpu else device
    mimi_encoder = MimiEncoder(device=mimi_device)

    # ---- optimizer + scheduler
    param_groups = get_param_groups(unwrapped, cfg["optim"])
    optimizer = torch.optim.AdamW(
        param_groups,
        weight_decay=cfg["train"]["weight_decay"],
        betas=(cfg["train"]["adam_beta1"], cfg["train"]["adam_beta2"]),
        eps=cfg["train"]["adam_eps"],
    )
    # scheduler_total_steps decouples the schedule horizon from run length so a
    # probe can replay a longer run's exact lr trajectory and stop early
    # (null -> max_steps, the normal single-knob behaviour).
    _sched_total = int(cfg["train"].get("scheduler_total_steps") or cfg["train"]["max_steps"])
    _schedule = str(cfg["train"].get("schedule", "cosine")).lower()
    if _schedule == "wsd":
        # Warmup-stable-decay: peak-LR plateau + short linear anneal, so every
        # plateau checkpoint is schedule-equivalent (early-stop friendly). For
        # an anneal-from-checkpoint run, resume the chosen plateau ckpt with
        # scheduler_total_steps = start_step + wsd_anneal_steps.
        scheduler = WSDScheduler(
            optimizer,
            warmup_steps=cfg["train"]["warmup_steps"],
            total_steps=_sched_total,
            anneal_steps=cfg["train"].get("wsd_anneal_steps"),
            anneal_frac=float(cfg["train"].get("wsd_anneal_frac", 0.1)),
            min_lr_ratio=cfg["train"]["min_lr_ratio"],
        )
    elif _schedule == "cosine":
        scheduler = WarmupCosineScheduler(
            optimizer,
            warmup_steps=cfg["train"]["warmup_steps"],
            total_steps=_sched_total,
            min_lr_ratio=cfg["train"]["min_lr_ratio"],
        )
    else:
        raise ValueError(f"unknown train.schedule {_schedule!r} (want cosine|wsd)")

    # Resume optimizer + scheduler state (AFTER FSDP wrap + optimizer creation).
    # fetch_checkpoint_file resolves GCS dirs to a local file -- the previous
    # os.path.exists(os.path.join("gs://...", "optimizer.pt")) check was ALWAYS
    # False for GCS resume, so every spot-preemption resume silently restarted
    # Adam moments from zero. Missing state is now a hard error: a long
    # production run must never quietly continue on a fresh optimizer
    # (train.allow_fresh_optimizer=true is the deliberate escape hatch).
    if start_step > 0 and resume_dir:
        opt_p = fetch_checkpoint_file(resume_dir, "optimizer.pt")
        if opt_p is None:
            if not bool(cfg["train"].get("allow_fresh_optimizer", False)):
                raise RuntimeError(
                    f"[resume] optimizer.pt missing under {resume_dir} -- refusing to "
                    f"resume step {start_step} with a fresh optimizer. Set "
                    f"train.allow_fresh_optimizer: true to override deliberately."
                )
            if is_main:
                print(
                    f"[resume] WARNING: optimizer.pt missing under {resume_dir}; "
                    f"continuing with a FRESH optimizer (allow_fresh_optimizer=true).",
                    flush=True,
                )
        else:
            full_osd = torch.load(opt_p, map_location="cpu", weights_only=True)
            try:
                from torch.distributed.fsdp import FullyShardedDataParallel as FSDP

                _is_fsdp = any(isinstance(m, FSDP) for m in fsdp_model.modules())
            except ImportError:
                _is_fsdp = False
            if _is_fsdp:
                # Reshard the full optimizer state for FSDP
                osd_to_load = FSDP.optim_state_dict_to_load(fsdp_model, optimizer, full_osd)
                optimizer.load_state_dict(osd_to_load)
            else:
                optimizer.load_state_dict(full_osd)
            del full_osd
            # Materialize the restored moments NOW, in their own graph. Without
            # this the CPU->XLA state transfer fuses into the FIRST post-resume
            # macro-step graph, whose transient buffers then overflow HBM on
            # configs near the ceiling (P0 resume drill, 2026-07-12: fresh b4
            # ran at 26.6/31.25GB; the resume of the SAME config OOM'd at step
            # 61 needing 14.9G with 14.5G free).
            backend.sync()
            if is_main:
                print(f"Restored optimizer state from {resume_dir}")
        # NOTE: scheduler state is intentionally NOT restored from the
        # checkpoint. WarmupCosineScheduler is a pure function of
        # (warmup_steps, total_steps, min_lr_ratio, base_lrs) -- it has no
        # other organic state -- and it was already freshly constructed
        # above from the CURRENT config. Restoring scheduler.pt would
        # silently clobber a deliberately-changed max_steps (e.g. extending
        # a run's horizon) back to the checkpoint's stale total_steps,
        # parking the LR at min_lr_ratio instead of actually training the
        # extended steps. The fresh construction is identical to the old
        # restored behavior on a same-config resume anyway.
        if is_main:
            print(f"Resuming training from step {start_step}")

    # Set the LR for the FIRST optimizer step. The loop only advances the
    # scheduler AFTER each optimizer step (scheduler.step(step + 1)), and
    # construction leaves the param groups at base (peak) LR -- without this
    # priming, the first step of every fresh start ran at peak LR instead of
    # warmup LR, and every resume applied one peak-LR update before the
    # schedule caught up.
    scheduler.step(start_step + 1)

    # ---- wandb
    # On a multi-host TPU pod (v4-32 = 4 hosts) every host calls this
    # block. Without coordination we get 4 separate runs all named the
    # same, with fragmented loss/system metrics. We use wandb shared-mode
    # (>= 0.19.9): the GLOBAL primary creates the run, broadcasts its
    # run-id via a GCS rendezvous file, and the 3 worker hosts attach
    # to the same run with x_primary=False. Result: ONE wandb dashboard
    # with global metrics from primary + per-host system stats labelled
    # rank_0..rank_3. Pattern: docs.wandb.ai/guides/track/log/
    # distributed-training#track-all-processes-to-a-single-run
    use_wandb = cfg["logging"]["use_wandb"]
    # Shared W&B run id (set by the multi-host rendezvous below on TPU). Initialised
    # here so it is always defined and can namespace the sweep checkpoint dir.
    run_id = None
    if use_wandb:
        import platform
        import re

        import wandb

        # --- Release reproducibility metadata (audit items #6, #8) -----
        # The VM is not a git checkout, so the commit SHA is injected by
        # the launcher via GIT_SHA. Versions + dataset provenance + split
        # counts make the public run reproducible.
        _versions = {"python": platform.python_version(), "torch": torch.__version__}
        for _m in ("torch_xla", "transformers", "peft", "numpy", "accelerate", "tokenizers"):
            try:
                _versions[_m] = __import__(_m).__version__
            except Exception:
                pass

        def _count_lines(_p):
            try:
                with open(_p) as _f:
                    return sum(1 for _ in _f)
            except Exception:
                return None

        _run_config = {
            **cfg,
            "release_meta": {
                "versions": _versions,
                "git_sha": os.environ.get("GIT_SHA", "unknown"),
                "git_dirty": os.environ.get("GIT_DIRTY", "unknown"),
                "tpu_topology": "v6e-8" if is_tpu else platform.machine(),
                "dataset_id": "tiny-aya-translate/tr-hi-mimi-encoded",
                "dataset_revision": os.environ.get("DATASET_REVISION", "unknown"),
                "train_rows": _count_lines(cfg["data"].get("train_split")),
                "val_rows": _count_lines(cfg["data"].get("val_split")),
            },
        }

        # Hygiene (audit item #9): never let secret-like content reach the
        # public run config. cfg is the YAML (clean by construction); this
        # is belt-and-suspenders before a public release.
        def _has_secret(obj):
            if isinstance(obj, dict):
                return any(_has_secret(k) or _has_secret(v) for k, v in obj.items())
            if isinstance(obj, (list, tuple)):
                return any(_has_secret(x) for x in obj)
            s = str(obj)
            # NB: deliberately do NOT flag bare 40-hex -- the git SHA we
            # intentionally log (and content hashes) are 40-hex and would
            # false-positive, aborting the run. HF tokens have a distinctive
            # hf_ prefix; named secrets are caught by substring.
            return bool(re.search(r"hf_[A-Za-z0-9]{20,}", s)) or any(
                t in s.upper() for t in ("WANDB_API_KEY", "HF_TOKEN", "KAGGLE_KEY", "AWS_SECRET")
            )

        assert not _has_secret(_run_config), "secret-like content in wandb config; aborting publish"

        _wandb_tags = [
            "stage2",
            "tr-hi",
            "speech-to-speech",
            "v6e-8" if is_tpu else "cpu",
            "release",
        ]
        _wandb_notes = (
            "TinyAya Stage 2 TR<->HI speech-to-speech translation. "
            f"git={os.environ.get('GIT_SHA', 'unknown')[:12]}. "
            "LoRA on CohereLabs/tiny-aya-base + Moshi depth decoder + Mimi."
        )

        try:
            host_idx = backend.host_index() if hasattr(backend, "host_index") else 0
        except Exception:
            host_idx = 0

        rendezvous_uri = os.environ.get(
            "WANDB_RENDEZVOUS_URI",
            f"gs://tinyaya-stage2-eu/wandb-rendezvous/{cfg['logging']['wandb_run_name']}.id",
        )

        if is_tpu and not is_main:
            # Worker host: wait for primary to publish run-id, then attach.
            run_id = None
            for _attempt in range(60):
                try:
                    import subprocess as _sp

                    out = _sp.run(
                        ["gsutil", "cat", rendezvous_uri],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if out.returncode == 0 and out.stdout.strip():
                        run_id = out.stdout.strip()
                        break
                except Exception:
                    pass
                time.sleep(5)

            if run_id:
                wandb.init(
                    project=cfg["logging"]["wandb_project"],
                    id=run_id,
                    settings=wandb.Settings(
                        mode="shared",
                        x_label=f"rank_{host_idx}",
                        x_primary=False,
                        x_update_finish_state=False,
                    ),
                    config=_run_config,
                )
                print(f"[wandb] worker host {host_idx} attached to shared run {run_id}", flush=True)
            else:
                print(
                    f"[wandb] worker host {host_idx} failed to find rendezvous; "
                    f"disabling wandb on this host",
                    flush=True,
                )
                use_wandb = False
        elif is_main:
            # Primary host: create (or RESUME) the run, publish run-id. On a spot
            # restart resume_wandb_run_id continues the same dashboard run.
            wandb.init(
                project=cfg["logging"]["wandb_project"],
                name=cfg["logging"]["wandb_run_name"],
                # Optional run group: lets a fleet of sibling runs (e.g. the v0.3
                # reval arms A..F) share one dashboard group. None = ungrouped
                # (prior behavior). Env WANDB_RUN_GROUP still overrides if set.
                group=cfg["logging"].get("wandb_group") or os.environ.get("WANDB_RUN_GROUP"),
                # Prefer a resumed id; else honor WANDB_RUN_ID (the sweep coordinator
                # pre-generates it so it can read this trial's metric back + so the
                # checkpoint dir is namespaced by the same id). else wandb generates.
                id=resume_wandb_run_id or os.environ.get("WANDB_RUN_ID") or None,
                # resume="allow" whenever an id is pinned (resumed OR coordinator's
                # deterministic WANDB_RUN_ID) so a RELAUNCH of a killed sweep trial
                # re-attaches to the same run instead of erroring on a duplicate id.
                resume=(
                    "allow" if (resume_wandb_run_id or os.environ.get("WANDB_RUN_ID")) else None
                ),
                config=_run_config,
                tags=_wandb_tags,
                notes=_wandb_notes,
                settings=wandb.Settings(
                    mode="shared",
                    x_label="rank_0",
                    x_primary=True,
                )
                if is_tpu
                else None,
            )
            # TPU note: wandb.log(data, step=N) is ignored in shared mode;
            # the _step counter auto-increments from 0 regardless. Use
            # define_metric with a custom step_metric so charts show actual
            # training step (10, 20, ..., 5000) instead of the internal
            # counter (0, 1, ..., 499).
            wandb.define_metric("global_step", hidden=True)
            wandb.define_metric("train/*", step_metric="global_step")
            wandb.define_metric("perf/*", step_metric="global_step")
            wandb.define_metric("val/*", step_metric="global_step")
            # NOTE: previously summary="min" here, so sweep trials could be
            # compared at their best point. Dropped: it makes W&B store the
            # run summary as {"min": x} instead of a flat scalar, which
            # breaks parallel-coordinates/line-chart panels (they read a
            # plain number). The actual best-value read for sweep ranking
            # goes through best_by_val/metadata.json (sweep_coordinator.py's
            # _read_metric_from_checkpoint), which never depended on this
            # summary aggregation, so dropping it is UI-only and safe.
            wandb.define_metric("val/composite", step_metric="global_step")
            wandb.define_metric("audio/*", step_metric="global_step")
            wandb.define_metric("mem/*", step_metric="global_step")
            wandb.define_metric("tpu/*", step_metric="global_step")
            # Stability dashboard (per-group grad/weight/update norms + RMS,
            # clip_coef, spike ratios). Was missing, so diag/* charted against
            # wall-clock _step instead of the training step.
            wandb.define_metric("diag/*", step_metric="global_step")
            if is_tpu:
                run_id = wandb.run.id
                try:
                    import subprocess as _sp
                    import tempfile as _tf

                    with _tf.NamedTemporaryFile("w", suffix=".id", delete=False) as f:
                        f.write(run_id)
                        local_path = f.name
                    _sp.run(
                        ["gsutil", "cp", local_path, rendezvous_uri],
                        check=False,
                        capture_output=True,
                        timeout=20,
                    )
                    print(
                        f"[wandb] primary published run_id={run_id} to {rendezvous_uri}", flush=True
                    )
                except Exception as e:
                    print(f"[wandb] primary failed to publish run_id: {e}", flush=True)
        else:
            # Non-main on single-host (CPU/GPU): no-op.
            use_wandb = False

    # ---- hub push config
    push_to_hub = cfg["logging"]["push_to_hub"] and is_main
    hub_repo_id = cfg["logging"]["hub_repo_id"]
    hub_token = os.environ.get("HF_TOKEN")

    # ---- training loop
    # save_dir may be a gs:// URL. Do NOT wrap it in pathlib.Path -- Path
    # collapses "gs://bucket/x" to "gs:/bucket/x", so mkdir/os.makedirs
    # silently write to a LOCAL directory named "gs:" and save_every
    # checkpoints never reach GCS. Keep it a str; the checkpointing helpers
    # stage to a temp dir and gsutil-upload when the dest is gs://. Only
    # create local destinations here.
    save_dir = str(cfg["logging"]["save_dir"])
    # Sweep trials share one save_dir from the proxy config; namespace it by the
    # (rendezvous-shared) W&B run id so every trial keeps ALL its checkpoints in an
    # isolated dir with no step-filename collisions across the sequential sweep. All
    # hosts share one run id via the GCS rendezvous, so the path is identical on
    # every host of the multi-host slice.
    # Capture the primary's W&B run id (also shared to workers via the rendezvous):
    # used to namespace sweep checkpoint dirs AND saved into each checkpoint so a
    # preempted run can resume the same W&B run (see resume block above).
    if run_id is None and use_wandb and getattr(wandb, "run", None) is not None:
        run_id = wandb.run.id
    if args.sweep and run_id:
        save_dir = save_dir.rstrip("/") + "/" + str(run_id)
        if is_main:
            print(f"[sweep] namespaced save_dir -> {save_dir}", flush=True)
    _save_is_gcs = save_dir.startswith("gs://")
    if not _save_is_gcs:
        Path(save_dir).mkdir(parents=True, exist_ok=True)

    def _ckpt_subpath(*parts: str) -> str:
        """Join checkpoint subpaths while preserving a gs:// prefix."""
        return "/".join([save_dir.rstrip("/"), *[str(p).strip("/") for p in parts]])

    # Audio demo WAVs cannot be written to gs:// by soundfile; keep them on
    # local disk (they are also logged to W&B). For a local save_dir they
    # live alongside the checkpoints.
    _artifacts_dir = Path(save_dir) if not _save_is_gcs else Path("/tmp/tinyaya_artifacts")

    if train_sampler is not None:
        train_sampler.set_epoch(0)
    data_iter = iter(train_loader)
    running = {"loss": 0.0, "text": 0.0, "audio": 0.0, "per_cb": torch.zeros(num_codebooks)}
    t0 = time.time()
    t_last = t0
    # Phase A early stopping: stop if val/loss hasn't improved by > min_delta for
    # `early_stop_patience` consecutive val cycles. patience=0 disables it.
    # NOTE: best_by_val is saved on every improvement regardless of patience, so
    # stopping NEVER degrades the released model -- it only halts the run (and a
    # longer patience can catch a late second-descent from the cosine LR decay).
    early_stop_patience = int(cfg["train"].get("early_stop_patience", 0))
    early_stop_min_delta = float(cfg["train"].get("early_stop_min_delta", 0.0))
    # best_val / patience survive a resume via the periodic checkpoint's
    # metadata -- otherwise the first post-preemption val would overwrite
    # best_by_val even when WORSE than the pre-preemption best, and the
    # early-stop countdown would silently reset.
    best_val = float(resume_meta.get("best_val", float("inf")))
    _patience_left = int(resume_meta.get("patience_left", early_stop_patience))
    if start_step > 0 and is_main and best_val != float("inf"):
        print(
            f"[resume] restored best_val={best_val:.4f}, "
            f"patience_left={_patience_left}",
            flush=True,
        )
    _early_stop = False

    grad_accum = cfg["train"]["grad_accum"]
    # Opt-in graph break after every micro-batch (see the mark_step call in
    # the micro loop). Default off: the one-graph-per-macro-step behaviour
    # is load-bearing for the tuned v6e-16 production path.
    micro_mark_step = bool(cfg["train"].get("micro_mark_step", False)) and is_tpu
    # XLA traces all grad-accum micro-batches into one macro-step graph.
    # Never let one macro-step straddle an epoch reset: that host-side
    # branch was the remaining step-259 topology risk after iter 24g.
    micro_batches_per_epoch = len(train_loader)
    usable_micro_batches_per_epoch = (
        (micro_batches_per_epoch // grad_accum) * grad_accum if is_tpu else micro_batches_per_epoch
    )
    micro_batches_seen_this_epoch = 0
    if is_tpu and usable_micro_batches_per_epoch == 0:
        raise RuntimeError(
            f"TPU train_loader has only {micro_batches_per_epoch} micro-batches, "
            f"less than grad_accum={grad_accum}"
        )
    step = start_step
    max_steps = cfg["train"]["max_steps"]
    log_every = cfg["logging"]["log_every"]
    save_every = cfg["logging"]["save_every"]
    # Log-spaced early checkpoints for the public mechanistic-interp suite
    # (Pythia convention: dense sampling of the fast early dynamics). Union of
    # an auto {1,2,4,...,512} schedule (logging.log_spaced_saves) and any
    # explicit logging.save_at_steps list. Saved IN ADDITION to save_every.
    save_at_steps = set(int(s) for s in (cfg["logging"].get("save_at_steps") or []))
    if cfg["logging"].get("log_spaced_saves", False):
        _p = 1
        while _p <= 512:
            save_at_steps.add(_p)
            _p *= 2
    # Checkpoint retention. keep_last_n<=0 => UNLIMITED (no rotation). When
    # keep_local_checkpoints is set, periodic + final checkpoints are also
    # mirrored to local_checkpoint_dir on the VM (disk-guarded in save_checkpoint).
    keep_last_n = cfg["logging"].get("keep_last_n", 5)
    keep_local_dir = (
        str(cfg["logging"].get("local_checkpoint_dir", "/mnt/data/checkpoints"))
        if cfg["logging"].get("keep_local_checkpoints", False)
        else None
    )
    # Background the multi-GB periodic-save upload so keep-all saves don't stall
    # the loop (best_by_val + final + canonical stay synchronous). Drained before
    # the final save so a released run never exits mid-upload.
    async_ckpt = bool(cfg["logging"].get("async_checkpoint_upload", False))
    audio_every = cfg["logging"]["audio_every"]
    val_every = cfg["logging"]["val_every"]
    text_w = cfg["loss"]["text_weight"]
    audio_w = cfg["loss"]["audio_weight"]
    text_pad_w = cfg["loss"].get("text_padding_weight", 0.01)
    zero_pad_w = cfg["loss"].get("zero_padding_weight", 0.0)
    # Phase A: label smoothing on the TRAIN loss only (val stays clean CE).
    label_smooth = cfg["loss"].get("label_smoothing", 0.0)
    # Phase D: text_weight curriculum (anneal start->end over the first frac of
    # the run). Quantised -> only a few distinct text_weight values occur, so XLA
    # recompiles a bounded number of times (a smooth per-step ramp would recompile
    # every step). Disabled (-> static text_w) when frac<=0 or start==end.
    _tw_start = float(cfg["loss"].get("text_weight_start", text_w))
    _tw_end = float(cfg["loss"].get("text_weight_end", text_w))
    _tw_frac = float(cfg["loss"].get("text_weight_curriculum_frac", 0.0))
    _tw_quantum = float(cfg["loss"].get("text_weight_quantum", 0.05))
    _tw_enabled = _tw_frac > 0 and _tw_start != _tw_end

    def _text_weight_for(s: int) -> float:
        """Train-loss text_weight for step ``s`` (curriculum, or static)."""
        if not _tw_enabled:
            return text_w
        return text_weight_at(s, max_steps, _tw_start, _tw_end, _tw_frac, _tw_quantum)

    if _tw_enabled:
        print(
            f"  [text-curriculum] text_weight {_tw_start}->{_tw_end} over first "
            f"{_tw_frac:.0%} of {max_steps} steps (quantum {_tw_quantum})",
            flush=True,
        )
    # Phase C: per-codebook loss weighting + progressive coarse->fine unmasking.
    # OFF unless configured (cb_weights=None -> uniform per-codebook mean = the v2
    # behaviour). When on, the [CB] weight vector is computed per step but CACHED by
    # value: identical vectors reuse one device tensor (one XLA graph), so only the
    # handful of distinct vectors during the unmask ramp recompile (one-time).
    _cb_multipliers = cfg["loss"].get("per_codebook_multipliers", None)
    _cb_unmask_frac = float(cfg["loss"].get("progressive_unmask_fraction", 0.0))
    _cb_unmask_k0 = int(cfg["loss"].get("unmask_k0", 1))
    _cb_enabled = _cb_multipliers is not None or _cb_unmask_frac > 0
    _cb_cache: dict[tuple, torch.Tensor] = {}

    def _cb_weights_for(s: int):
        """Device [CB] weight tensor for step ``s`` (cached by value), or None."""
        if not _cb_enabled:
            return None
        key = tuple(
            codebook_weights(
                s, max_steps, num_codebooks, _cb_multipliers, _cb_unmask_frac, _cb_unmask_k0
            )
        )
        t = _cb_cache.get(key)
        if t is None:
            t = torch.tensor(key, device=device, dtype=torch.float32)
            _cb_cache[key] = t
        return t

    perf_cfg = cfg.get("perf", {})
    perf_enabled = bool(perf_cfg.get("enabled", False))
    # P0 batch-semantics audit: print the actual XLA sharding annotation of the
    # first input batch once, so a smoke run shows what the mesh REALLY does to
    # the batch dim (list is a mutable one-shot latch for the closure below).
    debug_input_sharding = bool(cfg["train"].get("debug_input_sharding", False))
    _sharding_logged: list[bool] = []
    perf_warmup_skip_steps = int(perf_cfg.get("warmup_skip_steps", 50))
    perf_step_times: list[float] = []
    # Global optimizer batch. Single-host SPMD: the loader tensor IS the global
    # batch (P0 audit, spmd_batch_truth.py), so no world factor -> host_count=1.
    # Multi-host SPMD (v6e-16): batch_size is PER-HOST; the minibatch pipeline
    # assembles per_host x host_count across hosts. DDP (GPU): each rank loads
    # its own rows, so the world multiplier is real.
    effective_batch = cfg["train"]["batch_size"] * grad_accum * (
        n_hosts if is_tpu else max(1, backend.world_size())
    )
    frame_tokens_per_step = effective_batch * max_frames

    xprof_trace = None
    if is_tpu and bool(perf_cfg.get("xprof_trace_labels", False)):
        try:
            import torch_xla.debug.profiler as xp

            xprof_trace = xp.Trace
        except Exception as e:
            if is_main:
                print(f"[perf] xprof trace labels disabled: {e}", flush=True)

    def trace_ctx(name: str):
        # GPU analogue: torch.profiler.record_function. On TPU this only
        # emits labels when an external XProf capture is active.
        if is_tpu and name in {"logging_materialize", "mark_step", "optimizer_step"}:
            # xp.Trace scopes must be closed before xm.mark_step()/torch_xla.sync.
            # Otherwise torch_xla raises "Expecting scope to be empty" during
            # the step marker. Keep host/data/forward/backward labels for Phase
            # 5 profiling, but leave XLA's execution fence unwrapped.
            return contextlib.nullcontext()
        return xprof_trace(name) if xprof_trace else contextlib.nullcontext()

    replay_batches: deque[dict[str, torch.Tensor]] = deque()

    def next_train_batch(
        record_for_replay: list[dict[str, torch.Tensor]] | None = None,
    ) -> dict[str, torch.Tensor]:
        """Return the next host batch while preserving TPU epoch topology."""
        nonlocal data_iter, micro_batches_seen_this_epoch

        from_replay = bool(replay_batches)
        if from_replay:
            batch = replay_batches.popleft()
        else:
            try:
                batch = next(data_iter)
            except StopIteration:
                if train_sampler is not None:
                    train_sampler.set_epoch(step)
                data_iter = iter(train_loader)
                micro_batches_seen_this_epoch = 0
                batch = next(data_iter)
            if record_for_replay is not None:
                record_for_replay.append(batch)
        if is_tpu:
            micro_batches_seen_this_epoch += 1
        return batch

    def ensure_adamw_state_for_gradients() -> None:
        """Create AdamW moment tensors before the TPU warmup optimizer graph."""
        for group in optimizer.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                state = optimizer.state[p]
                if state:
                    continue
                state["step"] = torch.zeros((), dtype=torch.float32)
                state["exp_avg"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                state["exp_avg_sq"] = torch.zeros_like(p, memory_format=torch.preserve_format)

    def reset_optimizer_state() -> None:
        """Zero AdamW moments and step counters after compile warmup."""
        for state in optimizer.state.values():
            for key, value in state.items():
                if torch.is_tensor(value):
                    value.zero_()
                elif isinstance(value, (int, float)):
                    state[key] = type(value)(0)

    def trainable_weight_sentinel(
        max_tensors: int = 8,
        values_per_tensor: int = 16,
    ) -> list[float]:
        """Copy a tiny trainable-parameter sentinel for the warmup drift check."""
        chunks = []
        for p in model.parameters():
            if p.requires_grad:
                chunks.append(p.detach().flatten()[:values_per_tensor].float())
                if len(chunks) >= max_tensors:
                    break
        if not chunks:
            return []
        sentinel = torch.cat(chunks)
        if is_tpu:
            import torch_xla

            torch_xla.sync()
        return [float(v) for v in sentinel.cpu().tolist()]

    def run_macro_step(
        *,
        advance_scheduler: bool,
        ensure_optimizer_state: bool = False,
        record_for_replay: list[dict[str, torch.Tensor]] | None = None,
        compute_diag: bool = False,
    ) -> dict[str, object]:
        """Run one static grad-accum macro-step and return unlogged metrics.

        Notes:
            TPU note: compile warmup calls this with zero LR and
            ``advance_scheduler=False`` so XLA sees the same
            forward/backward/optimizer graph without advancing visible
            training state.
        """
        if is_tpu:
            micro_loss_sum_xla = torch.tensor(0.0, device=device)
            micro_text_xla = torch.tensor(0.0, device=device)
            micro_audio_xla = torch.tensor(0.0, device=device)
            # Accumulate per-codebook loss on-device too; it is
            # materialised once per log_every (see logging block), so it
            # adds no per-micro-step host sync / graph break.
            micro_per_cb_xla = torch.zeros(num_codebooks, device=device)
        else:
            micro_loss_sum = 0.0
            micro_text = 0.0
            micro_audio = 0.0
        micro_per_cb = torch.zeros(num_codebooks)
        for micro in range(grad_accum):
            sync_ctx = (
                contextlib.nullcontext() if micro == grad_accum - 1 else backend.no_sync(model)
            )
            with sync_ctx:
                with trace_ctx("data_fetch"):
                    batch = next_train_batch(record_for_replay)

                batch_audio = batch["audio_codes"]
                if is_tpu:
                    expected_batch = cfg["train"]["batch_size"]
                    seq_frames = int(batch_audio.shape[2])
                    allowed_frames = bucket_frames or (max_frames,)
                    if seq_frames not in allowed_frames:
                        raise RuntimeError(
                            "TPU bucket invariant violated: "
                            f"seq_frames={seq_frames} not in allowed={allowed_frames}"
                        )
                    expected_2d = (expected_batch, seq_frames)
                    expected_audio = (expected_batch, num_codebooks, seq_frames)
                    if batch_audio.shape[1] < num_codebooks:
                        raise RuntimeError(
                            f"TPU batch has {batch_audio.shape[1]} codebooks; "
                            f"expected at least {num_codebooks}"
                        )
                    if batch_audio.shape[1] != num_codebooks:
                        batch_audio = batch_audio[:, :num_codebooks, :].contiguous()
                    actual = {
                        "text_ids": tuple(batch["text_ids"].shape),
                        "audio_codes": tuple(batch_audio.shape),
                        "attention_mask": tuple(batch["attention_mask"].shape),
                        "loss_mask": tuple(batch["loss_mask"].shape),
                    }
                    if (
                        actual["text_ids"] != expected_2d
                        or actual["audio_codes"] != expected_audio
                        or actual["attention_mask"] != expected_2d
                        or actual["loss_mask"] != expected_2d
                    ):
                        raise RuntimeError(
                            "TPU static-shape invariant violated: "
                            f"expected text/mask/loss={expected_2d}, "
                            f"audio={expected_audio}; got {actual}"
                        )

                with trace_ctx("device_transfer"):
                    if multihost:
                        # Multi-host DP: shard each PER-HOST cpu tensor into the
                        # GLOBAL batch across hosts (minibatch=True). This is the
                        # cross-host assembly the single-host .to()+mark_sharding
                        # path lacks; slices (cb0, per-stream cb0) are taken on the
                        # resulting global device tensors.
                        text_ids = backend.shard_to_device(batch["text_ids"], ("fsdp", None))
                        all_codes = backend.shard_to_device(batch_audio, ("fsdp", None, None))
                        cb0 = all_codes[:, 0, :]
                        mask = backend.shard_to_device(batch["attention_mask"], ("fsdp", None))
                        loss_mask = backend.shard_to_device(batch["loss_mask"], ("fsdp", None))
                        if "user_audio_codes" in batch:
                            user_cb0 = backend.shard_to_device(
                                batch["user_audio_codes"][:, 0, :], ("fsdp", None)
                            )
                            model_cb0 = backend.shard_to_device(
                                batch["model_audio_codes"][:, 0, :], ("fsdp", None)
                            )
                            full_model_codes = backend.shard_to_device(
                                batch["model_audio_codes"], ("fsdp", None, None)
                            )
                        else:
                            user_cb0 = cb0
                            model_cb0 = None
                            full_model_codes = None
                    else:
                        text_ids = batch["text_ids"].to(device)
                        all_codes = batch_audio.to(device)
                        cb0 = all_codes[:, 0, :]
                        mask = batch["attention_mask"].to(device)
                        loss_mask = batch["loss_mask"].to(device)

                        # Parallel streams (Moshi-style)
                        if "user_audio_codes" in batch:
                            user_cb0 = batch["user_audio_codes"][:, 0, :].to(device)
                            model_cb0 = batch["model_audio_codes"][:, 0, :].to(device)
                            full_model_codes = batch["model_audio_codes"].to(device)
                        else:
                            user_cb0 = cb0
                            model_cb0 = None
                            full_model_codes = None

                        # Single-host input sharding (multi-host is already
                        # sharded by shard_to_device above).
                        if hasattr(backend, "mark_sharding"):
                            backend.mark_sharding(text_ids, ("fsdp", None))
                            backend.mark_sharding(all_codes, ("fsdp", None, None))
                            backend.mark_sharding(mask, ("fsdp", None))
                            backend.mark_sharding(loss_mask, ("fsdp", None))

                    # One-shot sharding-truth print (P0 audit + multi-host
                    # verification): the annotation string is graph METADATA, so
                    # reading it does not materialize the tensor. On multi-host it
                    # shows the GLOBAL logical shape (per_host x host_count).
                    if (
                        debug_input_sharding
                        and not _sharding_logged
                        and hasattr(backend, "get_sharding_spec")
                    ):
                        _sharding_logged.append(True)
                        print(
                            f"[sharding] text_ids logical shape="
                            f"{tuple(text_ids.shape)} "
                            f"spec={backend.get_sharding_spec(text_ids)}",
                            flush=True,
                        )

                with trace_ctx("forward_loss"):
                    with backend.autocast_context(dtype=torch.bfloat16):
                        output = model(
                            text_ids=text_ids,
                            audio_codes=user_cb0 if model_cb0 is not None else cb0,
                            model_audio_codes=model_cb0,
                            attention_mask=mask,
                            full_audio_codes=full_model_codes[:, :num_codebooks, :]
                            if full_model_codes is not None
                            else all_codes[:, :num_codebooks, :],
                            depth_chunk_size=depth_chunk,
                        )
                        text_logits, audio_logits, _ = output
                        audio_targets = (
                            full_model_codes[:, :num_codebooks, :]
                            if full_model_codes is not None
                            else all_codes[:, :num_codebooks, :]
                        )
                        losses = compute_hierarchical_translation_loss(
                            text_logits,
                            audio_logits,
                            text_ids,
                            audio_targets,
                            mask,
                            loss_mask,
                            text_weight=_text_weight_for(step),  # Phase D curriculum
                            audio_weight=audio_w,
                            text_padding_weight=text_pad_w,
                            zero_padding_weight=zero_pad_w,
                            label_smoothing=label_smooth,  # Phase A: train-only regularizer
                            cb_weights=_cb_weights_for(step),  # Phase C (None if disabled)
                        )
                loss = losses["loss"] / grad_accum
                with trace_ctx("backward"):
                    loss.backward()
            if is_tpu:
                micro_loss_sum_xla = micro_loss_sum_xla + losses["loss"].detach()
                micro_text_xla = micro_text_xla + losses["text_loss"].detach()
                micro_audio_xla = micro_audio_xla + losses["audio_loss"].detach()
                micro_per_cb_xla = micro_per_cb_xla + losses["per_codebook_loss"].detach()
                if micro_mark_step:
                    # Graph break per micro-batch. Without it, all grad_accum
                    # micro fwd+bwd passes trace into ONE program; under scan
                    # the resulting buffer-assignment problem fragments HBM
                    # catastrophically (observed 2026-07-08 on v6e-8: 81.08G
                    # "used" of which 66.87G was 82.5% fragmentation over
                    # 14.21G of real buffers). Numerics are identical --
                    # gradients accumulate in .grad across graphs -- and the
                    # 8 identical micro graphs compile once.
                    import torch_xla

                    torch_xla.sync()
            else:
                micro_loss_sum += losses["loss"].item()
                micro_text += losses["text_loss"].item()
                micro_audio += losses["audio_loss"].item()
                micro_per_cb += losses["per_codebook_loss"].detach().cpu()

        if ensure_optimizer_state:
            ensure_adamw_state_for_gradients()

        # macro-step -- gradient clipping.
        # On FSDPv2 SPMD, vanilla torch.nn.utils.clip_grad_norm_
        # deadlocks at the all-reduce barrier with heterogeneous
        # parameter groups (HF #41881, pytorch/xla #3424).
        # Single-host v6e-8 SPMD invalidates the cross-host deadlock
        # concern (no inter-host all-reduce), but the per-param
        # graph-break storm from vanilla clip_grad_norm_ remains
        # (~550 graph breaks per step under FSDPv2).
        #
        # iter 19 lever 6: re-enable gradient clipping on TPU using
        # variant 6a -- a fused single-graph clip that avoids .item()
        # and produces a single fused HLO computation. The pattern:
        #   1. Accumulate total_sq_norm from all grad tensors (fused)
        #   2. Compute clip_coef = max_norm / (total_norm + eps)
        #   3. Apply torch.where to conditionally scale grads
        #   4. Single xm.mark_step() fence for the entire clip
        # This populates the train/grad_norm wandb metric (was 0.0)
        # and detects exploding gradients, at ~5-15% throughput cost.
        if is_tpu:
            import torch_xla

            # iter 23: lever 6 (fused clip) is gated behind a config
            # flag. Both iter 21 (vanilla clip) and iter 22 (clip with
            # set_to_none=False + requires_grad iteration) OOM-crashed
            # at step 258 with an HLO temp of 89 GiB. The crash was
            # bit-deterministic across runs (same seed, same data) and
            # was triggered by a NEW graph hash compiled on the lever
            # 6 mark_step at step 258. Even after stabilising the
            # iteration set with requires_grad, FSDPv2 evidently still
            # reshards or otherwise produces a fresh graph for that
            # specific batch, and the new graph happens to need 5.7x
            # the steady-state HBM. Until we can root-cause that
            # recompile, this run keeps lever 6 OFF (matches iter 18c)
            # and trades the train/grad_norm metric for run stability.
            enable_clip = bool(cfg["train"].get("enable_clip_grad_norm", False))
            # iter 24: decouple grad-norm OBSERVABILITY from clipping.
            # The lever 6 OOM at step 258 was triggered by the in-place
            # grad scaling (torch.where + per-param mul_) interacting with
            # FSDPv2 resharding -- not by the read-only norm reduction.
            # log_grad_norm computes total_norm for the train/grad_norm
            # metric WITHOUT mutating grads and WITHOUT a separate
            # mark_step (it folds into the existing fence below and is
            # materialised only at the log boundary, so no per-step host
            # sync). Set log_grad_norm: false to restore the exact
            # iter-18c-stable behaviour (grad_norm hardwired to 0).
            log_grad_norm = bool(cfg["train"].get("log_grad_norm", True))
            if enable_clip or log_grad_norm:
                # max_grad_norm is the normalized value: load_config() copies
                # train.clip_grad_norm (the YAML spelling) over it, so both
                # keys work and the YAML one wins. Do NOT read clip_grad_norm
                # here — keep the aliasing in the single load_config() site.
                max_grad_norm = cfg["train"].get("max_grad_norm", 1.0)
                total_sq = torch.tensor(0.0, device=device)
                for p in model.parameters():
                    if not p.requires_grad:
                        continue
                    if p.grad is None:
                        p.grad = torch.zeros_like(p)
                    total_sq = total_sq + (p.grad.float() ** 2).sum()
                total_norm = total_sq.sqrt()
                if enable_clip:
                    clip_coef = max_grad_norm / (total_norm + 1e-6)
                    clip_coef = torch.where(clip_coef < 1.0, clip_coef, torch.ones_like(clip_coef))
                    for p in model.parameters():
                        if not p.requires_grad:
                            continue
                        if p.grad is None:
                            p.grad = torch.zeros_like(p)
                        p.grad.mul_(clip_coef)
                with trace_ctx("mark_step"):
                    torch_xla.sync()
                grad_norm = total_norm
            else:
                with trace_ctx("mark_step"):
                    torch_xla.sync()
                grad_norm = torch.tensor(0.0)
        else:
            grad_norm = torch.nn.utils.clip_grad_norm_(
                model.parameters(), cfg["train"]["max_grad_norm"]
            )
            if not torch.isfinite(torch.tensor(micro_loss_sum / grad_accum)):
                print(f"!!! Non-finite loss at step {step}. Aborting.")
                sys.exit(2)

        # Stability dashboard: per-group grad/param/Adam diagnostics, captured
        # here while grads are LIVE (before zero_grad) and only on log-boundary
        # macro-steps (compute_diag). On-device; materialised once at log time.
        diag_names, diag_vals = ([], None)
        if compute_diag:
            diag_names, diag_vals = _group_grad_diag(optimizer, device)

        with trace_ctx("optimizer_step"):
            backend.optimizer_step(optimizer)
            if advance_scheduler:
                scheduler.step(step + 1)
            # iter 22: keep grads allocated as zero (see top-of-loop
            # comment) so the next step's lever 6 clip sees the same
            # parameter set as this one.
            optimizer.zero_grad(set_to_none=False)

        if is_tpu:
            return {
                "loss_xla": micro_loss_sum_xla,
                "text_xla": micro_text_xla,
                "audio_xla": micro_audio_xla,
                "per_cb_xla": micro_per_cb_xla,
                "grad_norm": grad_norm,
                "diag_names": diag_names,
                "diag_vals": diag_vals,
            }
        return {
            "loss": micro_loss_sum,
            "text": micro_text,
            "audio": micro_audio,
            "per_cb": micro_per_cb,
            "grad_norm": grad_norm,
            "diag_names": diag_names,
            "diag_vals": diag_vals,
        }

    if is_main:
        # Print the EFFECTIVE clip value (post load_config normalization of
        # the clip_grad_norm/max_grad_norm alias) so a run log always shows
        # what the fused clip actually used — the dead-key incident hid a
        # clip-10 config silently running at 1.0.
        _clip_on = bool(cfg["train"].get("enable_clip_grad_norm", False))
        _clip_val = cfg["train"].get("max_grad_norm", 1.0)
        print(
            f"\n=== Training: {max_steps} steps, accum={grad_accum}, "
            f"batch={cfg['train']['batch_size']}, "
            f"global_batch={effective_batch}, "
            f"clip={_clip_val if _clip_on else 'OFF'} ==="
        )
    model.train()
    # iter 22: set_to_none=False keeps every .grad slot allocated as a
    # zero tensor between optimizer steps, so the lever 6 clip and any
    # FSDPv2 reduce-scatter sees a stable parameter set on EVERY step.
    # Default set_to_none=True can leave .grad=None for params that
    # didn't receive gradient flow this step, and that variance was
    # the trigger for the iter 21 OOM at step 258.
    optimizer.zero_grad(set_to_none=False)

    # On TPU/SPMD, calling .item() / .cpu() inside the training loop forces
    # an XLA materialise-and-transfer that BLOCKS until the entire lazy
    # graph compiles + executes. With heterogeneous LoRA + full_ft groups
    # and grad_accum=2, this can take 30-60 minutes per step (see
    # pytorch/xla #4203, #8020, troubleshooting "_local_scalar_dense
    # typically indicates CPU context access"). We keep the running
    # accumulators as XLA tensors and materialise once per log_every.
    if is_tpu:
        running_xla = {
            "loss": torch.tensor(0.0, device=device),
            "text": torch.tensor(0.0, device=device),
            "audio": torch.tensor(0.0, device=device),
            "per_cb": torch.zeros(num_codebooks, device=device),
        }

    # iter 19 lever 4 fix: profiler capture must happen from a SEPARATE
    # process, not from a background thread in the training process.
    # The in-process auto-capture failed with "Connection refused"
    # because xp.trace() could not connect to its own xp.start_server
    # (per pytorch/xla capture_profile.py pattern -- the server is
    # meant to be queried from an external process). The launcher
    # script now handles this by SSH'ing back and running
    # capture_profile.py after the first compile completes (~10 min).
    # xp.start_server(9012) at startup still works and is kept.

    compile_warmup_steps = int(cfg["train"].get("compile_warmup_steps", 0) or 0)
    if compile_warmup_steps < 0:
        raise ValueError("train.compile_warmup_steps must be >= 0")
    if compile_warmup_steps and start_step > 0:
        if is_main:
            print(
                f"[compile-warmup] skipped because resume start_step={start_step}",
                flush=True,
            )
    elif compile_warmup_steps and not is_tpu:
        if is_main:
            print("[compile-warmup] skipped because backend is not TPU", flush=True)
    elif compile_warmup_steps:
        if is_main:
            print(
                f"\n=== TPU compile warmup: {compile_warmup_steps} zero-LR macro-step(s) ===",
                flush=True,
            )
        warmup_replay: list[dict[str, torch.Tensor]] = []
        saved_lrs = [group["lr"] for group in optimizer.param_groups]
        saved_weight_decays = [group.get("weight_decay", 0.0) for group in optimizer.param_groups]
        sentinel_before = trainable_weight_sentinel()
        try:
            for group in optimizer.param_groups:
                group["lr"] = 0.0
                group["weight_decay"] = 0.0
            for _ in range(compile_warmup_steps):
                if (
                    is_tpu
                    and micro_batches_seen_this_epoch + grad_accum > usable_micro_batches_per_epoch
                ):
                    data_iter = iter(train_loader)
                    micro_batches_seen_this_epoch = 0
                run_macro_step(
                    advance_scheduler=False,
                    ensure_optimizer_state=True,
                    record_for_replay=warmup_replay,
                )
        finally:
            for group, lr, weight_decay in zip(
                optimizer.param_groups,
                saved_lrs,
                saved_weight_decays,
                strict=True,
            ):
                group["lr"] = lr
                group["weight_decay"] = weight_decay
        reset_optimizer_state()
        import torch_xla

        torch_xla.sync()
        optimizer.zero_grad(set_to_none=False)
        sentinel_after = trainable_weight_sentinel()
        # Tolerance-based drift check. Warmup runs at lr=0 AND wd=0, so a real
        # weight update is mathematically 0; but EXACT float equality is
        # fragile on TPU/bf16 (the same unchanged weights read through two
        # different XLA graphs can differ by rounding noise). Use a small
        # absolute tolerance so genuine drift (a mis-zeroed LR/WD group) still
        # trips it while bf16 read-noise does not.
        _drift = max(
            (abs(a - b) for a, b in zip(sentinel_after, sentinel_before)),
            default=0.0,
        )
        if _drift > 1e-2:
            raise RuntimeError(
                "TPU compile warmup changed trainable weights beyond tolerance: "
                f"max|delta|={_drift:.3e} before={sentinel_before[:4]} "
                f"after={sentinel_after[:4]}"
            )
        if is_main:
            print(f"[compile-warmup] weight-drift check OK (max|delta|={_drift:.3e})", flush=True)
        micro_batches_seen_this_epoch = 0
        replay_batches.extend(warmup_replay)
        if is_main:
            print(
                "[compile-warmup] complete; optimizer state reset and "
                f"{len(warmup_replay)} micro-batch(es) queued for visible training",
                flush=True,
            )

    # Stability-dashboard host-side EMA state (updated at log cadence) for the
    # loss/grad spike ratios and Adam-v drift. ``diag_metrics`` gates the extra
    # per-group on-device reductions (default on; cheap, log-boundary only).
    diag_enabled = bool(cfg["logging"].get("diag_metrics", True))
    _ema = {"loss": None, "grad": None, "v": {}}
    # Per-group element counts for the RMS variants (RMS = L2 / sqrt(numel)).
    # Group membership is fixed after setup, so this is host-static — computing
    # it once here costs nothing at log time and adds ZERO device ops.
    _numel_by = {
        g["name"]: sum(p.numel() for p in g["params"] if p.requires_grad)
        for g in optimizer.param_groups
        if "name" in g
    }

    while step < max_steps:
        if is_tpu and micro_batches_seen_this_epoch + grad_accum > usable_micro_batches_per_epoch:
            # Reshuffle on epoch rollover. All hosts reach the same `step`, so a
            # DistributedSampler.set_epoch(step) keeps their shards consistent
            # (divergent epochs would overlap/miss rows across hosts).
            if train_sampler is not None:
                train_sampler.set_epoch(step)
            data_iter = iter(train_loader)
            micro_batches_seen_this_epoch = 0

        macro = run_macro_step(
            advance_scheduler=True,
            compute_diag=(diag_enabled and (step + 1) % log_every == 0),
        )
        step += 1
        if step in (1, 2, 5, 10, 25, 50):
            if hasattr(backend, "diagnose"):
                backend.diagnose(f"step={step}")

        grad_norm = macro["grad_norm"]
        if is_tpu:
            running_xla["loss"] = running_xla["loss"] + macro["loss_xla"] / grad_accum
            running_xla["text"] = running_xla["text"] + macro["text_xla"] / grad_accum
            running_xla["audio"] = running_xla["audio"] + macro["audio_xla"] / grad_accum
            running_xla["per_cb"] = running_xla["per_cb"] + macro["per_cb_xla"] / grad_accum
        else:
            running["loss"] += macro["loss"] / grad_accum
            running["text"] += macro["text"] / grad_accum
            running["audio"] += macro["audio"] / grad_accum
            running["per_cb"] += macro["per_cb"] / grad_accum

        # ---- logging
        if step % log_every == 0:
            if is_tpu:
                import torch_xla

                # Single materialisation of all losses at log boundary.
                with trace_ctx("logging_materialize"):
                    torch_xla.sync()
                    avg = {
                        "loss": (running_xla["loss"] / log_every).item(),
                        "text": (running_xla["text"] / log_every).item(),
                        "audio": (running_xla["audio"] / log_every).item(),
                        "per_cb": (running_xla["per_cb"] / log_every).cpu().tolist(),
                    }
            else:
                avg = {
                    k: (v / log_every if k != "per_cb" else (v / log_every).tolist())
                    for k, v in running.items()
                }

            # ---- stability dashboard: per-group + spike metrics (host-side
            # derivation from the on-device bundle; one transfer per log step).
            diag_log: dict[str, float] = {}
            _dvals = macro.get("diag_vals")
            _dnames = macro.get("diag_names") or []
            if _dvals is not None and len(_dnames) > 0:
                _flat = _dvals.cpu().tolist()  # single host transfer for all groups
                gd = dict(zip(_dnames, _flat))
                _lr_by = {g["name"]: g["lr"] for g in optimizer.param_groups if "name" in g}
                for gname in sorted({k.split("/", 1)[1] for k in gd}):
                    gn = gd.get(f"grad_norm/{gname}", 0.0)
                    pn = gd.get(f"param_norm/{gname}", 0.0)
                    vm = gd.get(f"adam_v_mean/{gname}", 0.0)
                    nf = gd.get(f"nonfinite_grads/{gname}", 0.0)
                    un = gd.get(f"adam_update_norm/{gname}", 0.0)
                    lr = _lr_by.get(gname, 0.0)
                    diag_log[f"diag/grad_norm/{gname}"] = gn
                    diag_log[f"diag/param_norm/{gname}"] = pn
                    diag_log[f"diag/update_weight_ratio/{gname}"] = (lr * gn) / (pn + 1e-12)
                    diag_log[f"diag/adam_v_mean/{gname}"] = vm
                    diag_log[f"diag/nonfinite_grads/{gname}"] = nf
                    # RMS variants: sqrt(mean(x^2)) = L2 / sqrt(numel). Weight
                    # RMS answers "how big are this group's weights"; grad RMS
                    # is the POST-clip gradient scale; update_rms_est is the
                    # SGD-style lr*grad estimate; update_rms_adam is the true
                    # Adam step size lr*||m/(sqrt(v)+eps)||_rms (one step
                    # stale, no bias correction — see _group_grad_diag notes).
                    _rt = math.sqrt(_numel_by.get(gname, 0) or 1)
                    diag_log[f"diag/weight_rms/{gname}"] = pn / _rt
                    diag_log[f"diag/grad_rms/{gname}"] = gn / _rt
                    diag_log[f"diag/update_rms_est/{gname}"] = lr * gn / _rt
                    diag_log[f"diag/update_rms_adam/{gname}"] = lr * un / _rt
                    _pv = _ema["v"].get(gname)
                    if _pv:
                        diag_log[f"diag/adam_v_drift/{gname}"] = vm / (_pv + 1e-12)
                    _ema["v"][gname] = vm if _pv is None else 0.9 * _pv + 0.1 * vm
                    if nf > 0 and is_main:
                        print(
                            f"  [ALERT] {nf:.0f} non-finite grad elems in group "
                            f"'{gname}' (step {step})",
                            flush=True,
                        )
            # loss / grad spike ratios + non-finite guard (host EMA at log cadence)
            _lval = avg["loss"]
            _gval = float(grad_norm.item()) if hasattr(grad_norm, "item") else float(grad_norm)
            # Effective clip coefficient this step (train/grad_norm is the
            # PRE-clip global norm; the per-group diag norms are POST-clip, so
            # pre-clip group norms reconstruct as grad_rms / clip_coef).
            if bool(cfg["train"].get("enable_clip_grad_norm", False)) and _gval > 0:
                _mgn = float(cfg["train"].get("max_grad_norm", 1.0))
                diag_log["diag/clip_coef"] = min(1.0, _mgn / (_gval + 1e-6))
            if _ema["loss"] is not None:
                _ls = (_lval - _ema["loss"]) / (abs(_ema["loss"]) + 1e-9)
                _gs = _gval / (_ema["grad"] + 1e-9)
                diag_log["diag/loss_spike_ratio"] = _ls
                diag_log["diag/grad_spike_ratio"] = _gs
                if is_main and _ls > 0.10:
                    print(
                        f"  [ALERT] loss spike {_ls * 100:.0f}% (loss {_lval:.3f} "
                        f"vs EMA {_ema['loss']:.3f}) step {step}",
                        flush=True,
                    )
                if is_main and _gs > 3.0:
                    print(
                        f"  [ALERT] grad spike {_gs:.1f}x (grad {_gval:.2f} "
                        f"vs EMA {_ema['grad']:.2f}) step {step}",
                        flush=True,
                    )
            if is_main and not math.isfinite(_lval):
                print(f"  [ALERT] non-finite train loss at step {step}", flush=True)
            _ema["loss"] = _lval if _ema["loss"] is None else 0.9 * _ema["loss"] + 0.1 * _lval
            _ema["grad"] = _gval if _ema["grad"] is None else 0.9 * _ema["grad"] + 0.1 * _gval

            now = time.time()
            log_interval_sec = now - t_last
            step_time = log_interval_sec / log_every
            t_last = now
            perf_log = {}
            if perf_enabled:
                if step >= perf_warmup_skip_steps:
                    perf_step_times.append(step_time)
                perf_log = {
                    "perf/effective_batch": effective_batch,
                    "perf/examples_per_sec": effective_batch / step_time if step_time > 0 else 0,
                    "perf/frame_tokens_per_sec": (
                        frame_tokens_per_step / step_time if step_time > 0 else 0
                    ),
                    "perf/log_interval_sec": log_interval_sec,
                }
                p50 = _percentile(perf_step_times, 0.50)
                p90 = _percentile(perf_step_times, 0.90)
                p99 = _percentile(perf_step_times, 0.99)
                if p50 is not None:
                    perf_log.update(
                        {
                            "perf/p50_step_time": p50,
                            "perf/p90_step_time": p90,
                            "perf/p99_step_time": p99,
                            "perf/steady_window_steps": len(perf_step_times),
                        }
                    )
            lrs = {f"train/lr_{g['name']}": g["lr"] for g in optimizer.param_groups if "name" in g}
            mem_info = backend.get_memory_info()
            peak_gb = mem_info["max_allocated_gb"] if mem_info else 0
            alloc_gb = mem_info["allocated_gb"] if mem_info else 0
            hbm_available = mem_info.get("hbm_available", 0.0) if mem_info else 0.0
            host_rss_gb = _host_rss_gb()
            if is_main:
                print(
                    f"step {step:6d} | loss {avg['loss']:.4f} | "
                    f"text {avg['text']:.4f} audio {avg['audio']:.4f} | "
                    f"grad {grad_norm:.3f} | {step_time:.2f}s/step | "
                    f"peak {peak_gb:.1f}G | host_rss {host_rss_gb:.1f}G"
                )
                # Compact stability-dashboard line (visible in the log even when
                # W&B is off; full series go to diag/* in W&B).
                if diag_log:
                    _gn = " ".join(
                        f"{k.rsplit('/', 1)[1]}={diag_log[k]:.2f}"
                        for k in sorted(diag_log)
                        if k.startswith("diag/grad_norm/")
                    )
                    _nf = sum(
                        v for k, v in diag_log.items() if k.startswith("diag/nonfinite_grads/")
                    )
                    print(
                        f"  [diag] gradnorm {_gn} | "
                        f"spike L={diag_log.get('diag/loss_spike_ratio', 0.0):+.2f} "
                        f"G={diag_log.get('diag/grad_spike_ratio', 0.0):.2f} | "
                        f"nonfinite={_nf:.0f}",
                        flush=True,
                    )
            if use_wandb and is_main:
                import wandb

                log = {
                    "train/loss": avg["loss"],
                    "train/text_loss": avg["text"],
                    "train/audio_loss": avg["audio"],
                    "train/grad_norm": grad_norm.item(),
                    "perf/step_time": step_time,
                    "mem/peak_gb": peak_gb,
                    "mem/allocated_gb": alloc_gb,
                    "mem/hbm_available": hbm_available,
                    "host/rss_gb": host_rss_gb,
                    **perf_log,
                    **lrs,
                    **diag_log,
                }
                for i, v in enumerate(avg["per_cb"]):
                    log[f"train/per_codebook_loss_{i}"] = v
                # Per-chip HBM + duty-cycle timeseries (tpu/chip{i}/hbm_gib,
                # tpu/chip{i}/duty_pct, tpu/hbm_max_gib, ...). TPU backend
                # only; internally cached 30 s so calling every log step is
                # free. Multi-host note: reports the PRIMARY host's chips.
                per_chip = getattr(backend, "per_chip_metrics", None)
                if per_chip is not None:
                    log.update(per_chip())
                if args.sweep:
                    # Health flag so the sweep can auto-reject trials whose text
                    # stream is stuck at random (CE ~ ln(text_vocab) ~ 12.5).
                    log["sweep/text_ok"] = 1.0 if avg["text"] < 11.5 else 0.0
                log["global_step"] = step
                wandb.log(log)
            if is_tpu:
                running_xla = {
                    "loss": torch.tensor(0.0, device=device),
                    "text": torch.tensor(0.0, device=device),
                    "audio": torch.tensor(0.0, device=device),
                    "per_cb": torch.zeros(num_codebooks, device=device),
                }
            else:
                running = {
                    "loss": 0.0,
                    "text": 0.0,
                    "audio": 0.0,
                    "per_cb": torch.zeros(num_codebooks),
                }
                if mem_info:
                    torch.cuda.reset_peak_memory_stats()
            backend.sync()

        # ---- audio demo
        # Skip on TPU: generate_audio_sample contains an autoregressive
        # Python loop with `tok.cpu()` inside an inner per-codebook
        # loop (640 sync points) AND the backbone forward sees a
        # growing-by-1 sequence each iter, which forces a fresh XLA
        # compile per generation step. Empirically that locks the
        # main thread for 2-3 hours per call. The audio demo is a
        # qualitative sanity check, not a training requirement;
        # generate samples post-training on a GPU instead.
        is_distributed = int(os.environ.get("WORLD_SIZE", "1")) > 1
        if (
            audio_every
            and step % audio_every == 0
            and is_main
            and not is_tpu
            and not is_distributed
        ):
            try:
                r = generate_audio_sample(
                    unwrapped,
                    train_ds,
                    mimi_encoder,
                    device,
                    num_codebooks,
                    sample_idx=0,
                    max_target_frames=80,
                    backend=backend,
                )
                print(f"  demo cb0_acc={r['cb0_accuracy'] * 100:.1f}%")
                ad = _artifacts_dir / "audio_samples" / f"step_{step:06d}"
                ad.mkdir(parents=True, exist_ok=True)
                sf.write(ad / "source.wav", r["source_wav"], 24000)
                sf.write(ad / "target_gt.wav", r["target_gt_wav"], 24000)
                sf.write(ad / "generated.wav", r["generated_wav"], 24000)
                if use_wandb:
                    import wandb

                    wandb.log(
                        {
                            "global_step": step,
                            "audio/source": wandb.Audio(r["source_wav"], sample_rate=24000),
                            "audio/target_gt": wandb.Audio(r["target_gt_wav"], sample_rate=24000),
                            "audio/generated": wandb.Audio(r["generated_wav"], sample_rate=24000),
                            "audio/cb0_accuracy_train": r["cb0_accuracy"],
                        },
                    )
            except Exception as e:
                print(f"  demo failed: {e}")

        # ---- validation
        # run_validation was rewritten (patch-7 pattern) to be TPU-safe:
        # on-device accumulators, single end-of-pass host sync, no
        # recompiles, and confirmed NOT to tank throughput (v6e-8 smoke).
        # HOWEVER, the val forward still yields a non-finite loss at
        # supervised positions on TPU (every batch), a data/numerics issue
        # distinct from masking -- under investigation. So inline TPU val
        # is OPT-IN (`logging.val_on_tpu`, default false); release quality
        # comes from the GPU eval (eval_release.py: ASR-BLEU + DNSMOS),
        # which is the stronger signal anyway. On GPU, val runs as before.
        _val_enabled = (not is_tpu) or bool(cfg["logging"].get("val_on_tpu", False))
        if val_loader is not None and val_every and step % val_every == 0 and _val_enabled:
            if is_main:
                print(f"  running validation at step {step}...")
            val = run_validation(
                model,
                val_loader,
                device,
                num_codebooks,
                depth_chunk,
                cfg["loss"],
                is_ddp=False,
                backend=backend,
                max_batches=cfg["logging"].get("val_max_batches"),
                val_debug=cfg["logging"].get("val_debug", False),
            )
            # run_validation returns {} if every batch was non-finite -- a
            # failed/empty val must never crash the training run.
            val_ok = bool(val) and "val/loss" in val
            if val_ok and is_main:
                print(
                    f"  val/composite={val.get('val/composite', float('nan')):.4f} "
                    f"(text={val['val/text_loss']:.4f} audio={val['val/audio_loss']:.4f}) "
                    f"val/loss={val['val/loss']:.4f} cb0_acc={val['val/cb0_acc'] * 100:.1f}% "
                    f"text_acc={val.get('val/text_acc', 0.0) * 100:.1f}%"
                )
                _cba = val.get("val/per_codebook_acc")
                if _cba:
                    print(
                        "  [val] per-codebook acc: "
                        + " ".join(f"cb{i}={a * 100:.1f}%" for i, a in enumerate(_cba)),
                        flush=True,
                    )
            if val_ok and use_wandb and is_main:
                import wandb

                _list_keys = ("val/per_codebook_loss", "val/per_codebook_acc")
                log = {k: v for k, v in val.items() if k not in _list_keys}
                for i, v in enumerate(val["val/per_codebook_loss"]):
                    log[f"val/per_codebook_loss_{i}"] = v
                for i, v in enumerate(val.get("val/per_codebook_acc", [])):
                    log[f"val/per_codebook_acc_{i}"] = v
                log["global_step"] = step
                wandb.log(log)
            _improved = False
            if val_ok:
                # Phase D: select/early-stop on the composite (audio-heavier) metric;
                # fall back to raw val/loss if composite is absent (older configs).
                _stop_metric = val.get("val/composite", val.get("val/loss"))
                _dec = early_stop_step(
                    _stop_metric,
                    best_val,
                    _patience_left,
                    early_stop_patience,
                    early_stop_min_delta,
                )
                _improved, best_val, _patience_left = (
                    _dec.improved,
                    _dec.best_val,
                    _dec.patience_left,
                )
                if _dec.should_stop:
                    _early_stop = True
                if not _improved and early_stop_patience > 0 and is_main:
                    _tag = (
                        "STOPPING"
                        if _dec.should_stop
                        else (f"patience {max(_patience_left, 0)}/{early_stop_patience}")
                    )
                    print(
                        f"  [early-stop] no val improvement (>{early_stop_min_delta}); "
                        f"{_tag} (best {best_val:.4f})",
                        flush=True,
                    )
            if _improved:
                # Validation only runs on GPU (not is_tpu), where save_dir is
                # local; keep best_by_val as a local Path.
                best_dir = Path(save_dir) / "best_by_val"
                if is_main and best_dir.exists():
                    import shutil

                    shutil.rmtree(best_dir)
                # Patch 16/17: save_checkpoint runs on ALL hosts so the
                # SPMD .cpu() gather can complete; only is_main writes.
                save_checkpoint(
                    fsdp_model,
                    optimizer,
                    scheduler,
                    step,
                    str(best_dir),
                    extra_state={"best_val_loss": best_val, "config": cfg, "wandb_run_id": run_id},
                    is_main=is_main,
                )
                if is_main:
                    print(f"  * new best val — saved to {best_dir}")
                    if push_to_hub and hub_repo_id:
                        try:
                            push_checkpoint_to_hub(
                                str(best_dir),
                                hub_repo_id,
                                commit_message=f"best val {best_val:.4f} @ step {step}",
                                token=hub_token,
                            )
                        except Exception as e:
                            print(f"  hub push failed: {e}")
            backend.barrier()

        # ---- periodic save + prune (save_every cadence UNION log-spaced early)
        if (save_every and step % save_every == 0) or (step in save_at_steps):
            d = _ckpt_subpath(f"step_{step:06d}")
            # Patch 16/17: ALL hosts enter save_checkpoint to participate
            # in the SPMD .cpu() gather; only host-0 actually writes.
            save_checkpoint(
                fsdp_model,
                optimizer,
                scheduler,
                step,
                str(d),
                # best_val / patience_left ride every periodic checkpoint so a
                # resume restores the early-stop state (see loop setup).
                extra_state={
                    "config": cfg,
                    "wandb_run_id": run_id,
                    "best_val": best_val,
                    "patience_left": _patience_left,
                },
                is_main=is_main,
                keep_local_dir=keep_local_dir,
                async_upload=async_ckpt,
            )
            if is_main:
                # keep_last_n<=0 => prune_checkpoints no-ops (unlimited retention).
                prune_checkpoints(save_dir, keep_last=keep_last_n, keep_best="best_by_val")
                if push_to_hub and hub_repo_id:
                    try:
                        push_checkpoint_to_hub(
                            str(d), hub_repo_id, commit_message=f"step {step}", token=hub_token
                        )
                    except Exception as e:
                        print(f"  hub push failed: {e}")
            backend.barrier()

        if _early_stop:
            break  # Phase A early stopping -> fall through to the final save below

    # Drain any in-flight async periodic-save uploads before the final/canonical
    # saves so the released run never exits with an incomplete upload in GCS.
    if async_ckpt:
        from src.training.checkpointing import wait_for_uploads

        wait_for_uploads()

    # ---- final save (multi-host SPMD-safe; see patch 16/17)
    # patch 18b: respect save_every=0 escape hatch -- skip the final save
    # if periodic saves were disabled. Iter 9+10 deadlocked all 4 hosts
    # at save_checkpoint() despite patch 16/17 moving the .cpu() gather
    # outside the is_main gate; root-cause is a deeper XLA<->PEFT
    # interaction (likely safetensors serialization triggering an XLA
    # collective inside PEFT.save_pretrained). For the canary we want
    # to first validate that the training loop itself reaches step 200,
    # so this gate stays even at the final-save site.
    if save_every:
        d = _ckpt_subpath(f"step_{step:06d}")
        save_checkpoint(
            fsdp_model,
            optimizer,
            scheduler,
            step,
            str(d),
            extra_state={
                "config": cfg,
                "final": True,
                "wandb_run_id": run_id,
                "best_val": best_val,
                "patience_left": _patience_left,
            },
            is_main=is_main,
            keep_local_dir=keep_local_dir,
        )

    # patch 19: end-of-training canonical save (HF transformers issue
    # #36004 fix). Opt-in via cfg.train.final_canonical_save. This
    # bypasses the save_every gate -- with save_every=0 (patch 18a),
    # this is the only chance to land a checkpoint in GCS. Destructive:
    # model.to("cpu") loses FSDPv2 sharding metadata, so this only runs
    # once at the very end of training. ALL hosts must reach this call;
    # the SPMD gather inside .to("cpu") deadlocks if any host skips it.
    if cfg["train"].get("final_canonical_save", False):
        from src.training.checkpointing import save_checkpoint_canonical_final

        d_final = _ckpt_subpath(f"step_{step:06d}_final")
        if is_main:
            print(f"\n[patch 19] entering canonical final save -> {d_final}")
        save_checkpoint_canonical_final(unwrapped, str(d_final), is_main=is_main)
        if is_main:
            print("[patch 19] canonical final save complete")
    if is_main:
        print(f"\nTraining complete: {step} steps in {(time.time() - t0) / 60:.1f} min")
        if save_every and push_to_hub and hub_repo_id:
            try:
                push_checkpoint_to_hub(
                    str(d), hub_repo_id, commit_message=f"final step {step}", token=hub_token
                )
            except Exception as e:
                print(f"  hub push failed: {e}")
    if use_wandb and is_main:
        import wandb

        wandb.finish()

    backend.barrier()


if __name__ == "__main__":
    main()
