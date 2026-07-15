"""Inference latency: RTF + time-to-first-audible-frame (TTFA).

Methodology ported from codec-finetuning's TTFAT stage: perf_counter_ns
bracketed by device sync, warmup passes excluded, stats over n runs. The
evaluator passes generation callables so this module stays model-agnostic:

- ``full_fn()``  -> generates the full target and returns the frame count;
- ``first_fn()`` -> generates exactly ONE frame (TTFA: how long until the
  first audible frame could reach a listener).

RTF = wall_seconds / generated_audio_seconds (frames / 12.5 Hz). RTF < 1
means faster than real time. Numbers are hardware-specific: results.json
records the device string next to them.
"""

from __future__ import annotations

import time
from statistics import mean, median


def _sync(device: str) -> None:
    if device.startswith("cuda"):
        import torch

        torch.cuda.synchronize()


def timed_runs(fn, device: str, warmup: int = 1, runs: int = 3) -> list[float]:
    """Wall-clock seconds per run of ``fn`` (device-synced, warmup excluded)."""
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(runs):
        _sync(device)
        t0 = time.perf_counter_ns()
        fn()
        _sync(device)
        out.append((time.perf_counter_ns() - t0) / 1e9)
    return out


def latency_summary(
    full_fn,
    first_fn,
    frames: int,
    device: str,
    frame_rate_hz: float = 12.5,
    warmup: int = 1,
    runs: int = 3,
) -> dict:
    """RTF over the full generation + TTFA from a single-frame generation."""
    full_s = timed_runs(full_fn, device, warmup=warmup, runs=runs)
    first_s = timed_runs(first_fn, device, warmup=warmup, runs=runs)
    audio_s = frames / frame_rate_hz
    return {
        "device": device,
        "frames": frames,
        "audio_s": audio_s,
        "gen_wall_s_mean": mean(full_s),
        "gen_wall_s_median": median(full_s),
        "rtf": mean(full_s) / audio_s if audio_s > 0 else float("inf"),
        "ttfa_s_mean": mean(first_s),
        "ttfa_s_median": median(first_s),
        "per_frame_s": mean(full_s) / frames if frames else float("inf"),
        "runs": runs,
    }
