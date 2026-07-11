"""Linear-warmup LR schedulers: cosine decay and warmup-stable-decay (WSD).

WHY THIS EXISTS
---------------
``WarmupCosineScheduler`` is the standard recipe for transformer
fine-tuning: ramp the LR linearly from 0 to ``base_lr`` over the
warmup window, then decay along a cosine to ``min_lr_ratio * base_lr``
by ``total_steps``.

``WSDScheduler`` (warmup -> stable plateau -> short linear anneal, the
MiniCPM/trapezoid recipe) exists for the v0.3 long-horizon run with
early stopping: a cosine committed to ``total_steps`` leaves every
early-stopped checkpoint un-annealed (mid-cosine LR), whereas WSD holds
peak LR for the whole plateau so ANY plateau checkpoint is
schedule-equivalent, then anneals only in the final window.
Stop-anytime anneal-from-checkpoint needs no extra machinery: resume
the chosen plateau checkpoint with ``scheduler_total_steps =
start_step + anneal_steps`` and ``wsd_anneal_steps = anneal_steps`` --
the plateau ends exactly at the resume point and the run spends its
remaining budget annealing.

Both classes deliberately do *not* inherit from
``torch.optim.lr_scheduler._LRScheduler`` -- the parent's hidden
``last_epoch`` accounting confuses our explicit ``step(int)`` API
and needlessly complicates checkpoint state. They are pure functions
of their constructor args, so resume rebuilds them from config instead
of restoring state (see the resume block in train_hierarchical.py).

This file is device-agnostic; nothing inside touches CUDA or XLA.
"""

import math


class WarmupCosineScheduler:
    def __init__(self, optimizer, warmup_steps: int, total_steps: int, min_lr_ratio: float = 0.0):
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps
        self.min_lr_ratio = min_lr_ratio
        self.base_lrs = [group["lr"] for group in optimizer.param_groups]

    def get_lr_multiplier(self, step: int) -> float:
        if step < self.warmup_steps:
            return step / max(1, self.warmup_steps)
        progress = (step - self.warmup_steps) / max(1, self.total_steps - self.warmup_steps)
        progress = min(progress, 1.0)
        cosine_decay = 0.5 * (1.0 + math.cos(math.pi * progress))
        return self.min_lr_ratio + (1.0 - self.min_lr_ratio) * cosine_decay

    def step(self, step: int):
        m = self.get_lr_multiplier(step)
        for group, base_lr in zip(self.optimizer.param_groups, self.base_lrs, strict=True):
            group["lr"] = base_lr * m

    def get_last_lrs(self) -> list[float]:
        return [group["lr"] for group in self.optimizer.param_groups]

    def state_dict(self) -> dict:
        return {
            "base_lrs": self.base_lrs,
            "warmup_steps": self.warmup_steps,
            "total_steps": self.total_steps,
            "min_lr_ratio": self.min_lr_ratio,
        }

    def load_state_dict(self, sd: dict):
        self.base_lrs = sd["base_lrs"]
        self.warmup_steps = sd["warmup_steps"]
        self.total_steps = sd["total_steps"]
        self.min_lr_ratio = sd["min_lr_ratio"]


class WSDScheduler:
    """Warmup -> stable plateau at peak LR -> linear anneal to min_lr_ratio.

    Parameters
    ----------
    optimizer : torch.optim.Optimizer
        Param groups whose ``lr`` this scheduler drives (their construction
        ``lr`` values are the per-group peak LRs).
    warmup_steps : int
        Linear ramp 0 -> peak over this many steps.
    total_steps : int
        Step at which the anneal reaches ``min_lr_ratio * base_lr``.
    anneal_steps : int | None
        Length of the final linear anneal window. ``None`` derives it from
        ``anneal_frac``. The plateau spans
        ``[warmup_steps, total_steps - anneal_steps)``.
    anneal_frac : float
        Fallback anneal length as a fraction of ``total_steps`` (MiniCPM
        uses ~10%). Ignored when ``anneal_steps`` is given.
    min_lr_ratio : float
        Floor multiplier at ``total_steps`` (0.0 anneals to exactly 0).
    """

    def __init__(
        self,
        optimizer,
        warmup_steps: int,
        total_steps: int,
        anneal_steps: int | None = None,
        anneal_frac: float = 0.1,
        min_lr_ratio: float = 0.0,
    ):
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps
        if anneal_steps is None:
            anneal_steps = max(1, int(round(total_steps * anneal_frac)))
        self.anneal_steps = int(anneal_steps)
        self.min_lr_ratio = min_lr_ratio
        # the anneal never starts before warmup ends
        self.anneal_start = max(self.warmup_steps, total_steps - self.anneal_steps)
        self.base_lrs = [group["lr"] for group in optimizer.param_groups]

    def get_lr_multiplier(self, step: int) -> float:
        if step < self.warmup_steps:
            return step / max(1, self.warmup_steps)
        if step <= self.anneal_start:
            return 1.0
        progress = (step - self.anneal_start) / max(1, self.total_steps - self.anneal_start)
        progress = min(progress, 1.0)
        return 1.0 - (1.0 - self.min_lr_ratio) * progress

    def step(self, step: int):
        m = self.get_lr_multiplier(step)
        for group, base_lr in zip(self.optimizer.param_groups, self.base_lrs, strict=True):
            group["lr"] = base_lr * m

    def get_last_lrs(self) -> list[float]:
        return [group["lr"] for group in self.optimizer.param_groups]

    def state_dict(self) -> dict:
        return {
            "base_lrs": self.base_lrs,
            "warmup_steps": self.warmup_steps,
            "total_steps": self.total_steps,
            "anneal_steps": self.anneal_steps,
            "min_lr_ratio": self.min_lr_ratio,
        }

    def load_state_dict(self, sd: dict):
        self.base_lrs = sd["base_lrs"]
        self.warmup_steps = sd["warmup_steps"]
        self.total_steps = sd["total_steps"]
        self.anneal_steps = sd["anneal_steps"]
        self.min_lr_ratio = sd["min_lr_ratio"]
        self.anneal_start = max(self.warmup_steps, self.total_steps - self.anneal_steps)
