"""Tests for the multi-host SPMD data-parallel input pipeline (Phase A).

WHY THIS EXISTS
---------------
v6e-16 = 4 hosts x 4 chips. The old trainer collapsed a multi-host slice to
ONE host's rows (each host mark_sharding'd its batch as the whole global
batch; peers discarded). The fix, verified live on a 4-host mesh
(scripts/tpu/spmd_minibatch_truth.py: per-host (8,4) -> global (32,4), all 4
hosts' distinct rows assembled), is a DistributedSampler per host +
backend.shard_to_device (minibatch=True). These CPU/AST tests pin the wiring
so it can't silently regress back to the single-host UB. The on-device
assembly itself is validated by the live probe (Phase E), not here.

Run: ``python -m pytest tests/test_multihost_dp.py -v``
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = (REPO / "scripts" / "train_hierarchical.py").read_text()
_BACKEND = (REPO / "src" / "backend" / "tpu_backend.py").read_text()


def test_backend_exposes_multihost_primitives():
    # mesh accessor + set_global_mesh registration
    assert "def mesh(self)" in _BACKEND
    assert "xs.set_global_mesh(self._mesh)" in _BACKEND
    # per-host identity + local chip count for the minibatch divisibility guard
    assert "def process_index(self)" in _BACKEND
    assert "def local_chip_count(self)" in _BACKEND
    # the DP primitive: minibatch shard_to_device
    assert "def shard_to_device(self" in _BACKEND
    assert "minibatch=True" in _BACKEND
    assert "send_cpu_data_to_device" in _BACKEND


def test_multihost_flag_gates_the_pipeline():
    assert "multihost = is_tpu_early and n_hosts > 1" in _TRAIN
    # sampler branch: multihost uses a rank/replicas DistributedSampler
    assert "num_replicas=n_hosts, rank=_rank, shuffle=True, drop_last=True" in _TRAIN
    # bucket-frames + multihost is explicitly refused (sampler not host-aware)
    assert "bucket_frames + multi-host TPU is unsupported" in _TRAIN


def test_train_and_val_use_shard_to_device_on_multihost():
    # train loop device transfer branches on multihost
    assert _TRAIN.count("backend.shard_to_device(") >= 8  # train (4+3) + val (4+3)
    # val path mirrors train (else val collapses to one host's rows)
    assert "_mh = (" in _TRAIN
    # single-host path keeps .to(device)+mark_sharding
    assert "backend.mark_sharding(text_ids" in _TRAIN


def test_set_epoch_called_on_rollover_for_consistent_shards():
    # both the inner and the outer epoch rollover must set_epoch(step) so all
    # hosts reshuffle identically (divergent epochs overlap/miss rows)
    assert _TRAIN.count("train_sampler.set_epoch(step)") >= 2


def test_seed_note_documents_pjrt_local_rank_gap():
    # LOCAL_RANK is unset under PJRT SPMD; the DistributedSampler (not this
    # seed) is what makes hosts distinct -- documented so it isn't "fixed" wrong
    assert "LOCAL_RANK is unset" in _TRAIN


def test_resolve_loader_batch_is_per_host():
    tree = ast.parse(_TRAIN)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_loader_batch":
            ns: dict = {}
            exec(ast.get_source_segment(_TRAIN, node), ns)
            f = ns["resolve_loader_batch"]
            # v6e-16 recipe: per_chip 2 -> per-host 8 (not global 32)
            assert f({"per_chip_batch": 2, "batch_size": 4}, 16, 4) == 8
            return
    raise AssertionError("resolve_loader_batch not found")
