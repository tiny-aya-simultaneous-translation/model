"""Tests for the pre-launch hardening pass (long-horizon v6e-16 run).

WHY THIS EXISTS
---------------
The 2026-07-14 pre-launch audit found two silent failure modes (a contentless
``.unpacked`` staging marker that lets a tarball swap train on stale data, and
the zero-text alignment fallback) plus follow-on hardening: a checkpoint
integrity manifest in ``metadata.json``, a decoupled val loader batch
(``logging.val_per_chip_batch`` -- val is inference-only, so a bigger val
batch only shortens the val cycle and can never touch the LOCKED train batch
of 32), and HBM-capacity batch arithmetic for the probe matrix. These tests
pin the shell/trainer wiring and the pure-Python helpers.

Run: ``python -m pytest tests/test_hardening_prelaunch.py -v``
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock

REPO = pathlib.Path(__file__).resolve().parents[1]
_TRAIN = REPO / "scripts" / "train_hierarchical.py"
_TRAIN_SRC = _TRAIN.read_text()
_STARTUP_SRC = (REPO / "scripts" / "tpu" / "startup_script.sh").read_text()
_STAGE_SRC = (REPO / "scripts" / "tpu" / "stage_dataset.sh").read_text()
_PREFETCH_SRC = (REPO / "scripts" / "tpu" / "prefetch_backbones.sh").read_text()


def _resolve():
    """AST-extract resolve_loader_batch (no heavy train-script imports)."""
    tree = ast.parse(_TRAIN_SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_loader_batch":
            ns: dict = {}
            exec(ast.get_source_segment(_TRAIN_SRC, node), ns)
            return ns["resolve_loader_batch"]
    raise AssertionError("resolve_loader_batch not found")


def _load_ckpt():
    """Import src/training/checkpointing.py with a stub `torch` (CPU-only CI)."""
    for name in ("torch",):
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
    path = REPO / "src" / "training" / "checkpointing.py"
    spec = importlib.util.spec_from_file_location("checkpointing_hardening", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# §3.8 -- HBM capacity / val-batch arithmetic
# ---------------------------------------------------------------------------


def test_capacity_ladder_per_host_batches_v6e16():
    """b2/b4/b8 per chip on 4x4 v6e-16 -> per-host 8/16/32, all minibatch-divisible."""
    f = _resolve()
    for per_chip, per_host in ((2, 8), (4, 16), (8, 32)):
        got = f({"batch_size": 4, "per_chip_batch": per_chip}, n_chips=16, n_hosts=4)
        assert got == per_host
        # ShardingSpec(minibatch=True) guard: per-host batch % local_chips == 0
        assert got % 4 == 0


def test_val_batch_override_uses_same_resolution():
    """The val knob resolves through the SAME path as train (dict override)."""
    f = _resolve()
    train_cfg = {"batch_size": 4, "per_chip_batch": 2}
    # v6e-16: train per-host 8; val_per_chip_batch 8 -> val per-host 32.
    assert f(train_cfg, n_chips=16, n_hosts=4) == 8
    assert f({**train_cfg, "per_chip_batch": 8}, n_chips=16, n_hosts=4) == 32
    # v6e-8 single host: val per-host == global val batch.
    assert f({**train_cfg, "per_chip_batch": 8}, n_chips=8, n_hosts=1) == 64


def test_trainer_wires_val_batch_and_collator():
    """val loader must consume val_batch_size + val_collator, not train's."""
    assert 'batch_size=val_batch_size' in _TRAIN_SRC
    assert 'collate_fn=val_collator' in _TRAIN_SRC
    # knob read from logging, resolved via the train path, TPU-SPMD-only
    assert 'cfg["logging"].get("val_per_chip_batch")' in _TRAIN_SRC
    assert '"per_chip_batch": cfg["logging"]["val_per_chip_batch"]' in _TRAIN_SRC
    assert "val_per_chip_batch is TPU-SPMD-only" in _TRAIN_SRC
    # val collator pads the batch axis to the VAL batch
    assert "batch_pad_to=val_batch_size" in _TRAIN_SRC


# ---------------------------------------------------------------------------
# §2a -- checkpoint integrity manifest
# ---------------------------------------------------------------------------


def test_build_file_manifest(tmp_path):
    ckpt = _load_ckpt()
    (tmp_path / "optimizer.pt").write_bytes(b"x" * 10)
    (tmp_path / "metadata.json").write_text("{}")  # the gate: excluded
    sub = tmp_path / "peft_adapter"
    sub.mkdir()
    (sub / "adapter_model.safetensors").write_bytes(b"y" * 7)
    # a nested metadata.json (not the gate) IS manifest content
    (sub / "metadata.json").write_bytes(b"z" * 3)

    manifest = ckpt.build_file_manifest(str(tmp_path))
    assert manifest["optimizer.pt"] == 10
    assert manifest[str(pathlib.Path("peft_adapter") / "adapter_model.safetensors")] == 7
    assert manifest[str(pathlib.Path("peft_adapter") / "metadata.json")] == 3
    assert "metadata.json" not in manifest


def test_save_checkpoint_stamps_manifest():
    """save_checkpoint must build the manifest into metadata (source wiring)."""
    src = (REPO / "src" / "training" / "checkpointing.py").read_text()
    assert 'meta["files"] = build_file_manifest(write_dir)' in src


# ---------------------------------------------------------------------------
# §3.1/§3.2/§3.3 -- startup staging identity, preflight, HF offline
# ---------------------------------------------------------------------------


def test_stage_marker_records_identity():
    # marker content is read and compared against the requested source
    assert 'head -n1 "$_marker"' in _STAGE_SRC
    assert '[ "$_staged_src" != "$SWEEP_DATA_GS_URI" ]' in _STAGE_SRC
    assert '[ "$_staged_src" != "hf:$HF_DATASET" ]' in _STAGE_SRC
    # mismatch wipes the stale corpus before re-staging
    assert 'wiping stale corpus' in _STAGE_SRC
    # identity is written INTO the marker (both branches), never a bare touch
    assert "printf '%s\\nn_pt=%s\\n' \"$SWEEP_DATA_GS_URI\"" in _STAGE_SRC
    assert "printf 'hf:%s\\nn_pt=%s\\n' \"$HF_DATASET\"" in _STAGE_SRC
    assert 'touch "$DATA_DIR/encoded/.unpacked"' not in _STAGE_SRC


def test_stage_preflight_gates():
    # gates are env-driven (startup passes the metadata values through)
    assert 'EXPECTED_TRAIN_ROWS="${EXPECTED_TRAIN_ROWS:-0}"' in _STAGE_SRC
    assert 'MIN_TEXT_COVERAGE="${MIN_TEXT_COVERAGE:-0}"' in _STAGE_SRC
    # both gates refuse to launch (exit 1), not just warn
    assert _STAGE_SRC.count('[preflight] FATAL') == 2
    # digest written for the rendezvous marker
    assert '.data_digest' in _STAGE_SRC


def test_startup_delegates_staging_and_rides_digest():
    # startup calls the extracted script with the metadata gates...
    assert 'bash "$REPO_DIR/scripts/tpu/stage_dataset.sh"' in _STARTUP_SRC
    assert 'read_meta expected-train-rows 0' in _STARTUP_SRC
    assert 'read_meta min-text-coverage 0' in _STARTUP_SRC
    # ...reads the digest and refuses to launch on divergence
    assert '.data_digest' in _STARTUP_SRC
    assert 'DATA_DIGEST' in _STARTUP_SRC
    assert 'dataset digests DIVERGE' in _STARTUP_SRC
    # the old inline staging is gone (single source of truth)
    assert 'tar -xzf /tmp/sweep_subset.tar.gz' not in _STARTUP_SRC


# ---------------------------------------------------------------------------
# per-host TPU telemetry (all 16 chips via 4 labeled host streams)
# ---------------------------------------------------------------------------


def test_tpu_info_hbm_table_parser():
    """Parse both live tpu-info cell formats; skip headers and N/A rows.

    TORCH-FREE (CI runs without torch): the parser is pure regex, so it is
    AST-extracted from the class body instead of importing the module (whose
    top-level ``import torch`` would fail on the lightweight runner).
    """
    import re as _re

    src = (REPO / "src" / "backend" / "tpu_backend.py").read_text()
    tree = ast.parse(src)
    fn_src = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_tpu_info_hbm_table":
            fn_src = ast.get_source_segment(src, node)
    assert fn_src, "_parse_tpu_info_hbm_table not found"
    # dedent the method body (class-level indentation) before exec
    import textwrap

    ns: dict = {"re": _re}
    exec(textwrap.dedent(fn_src), ns)
    parse = ns["_parse_tpu_info_hbm_table"]

    live_format = """TPU HBM Usage
| Device | HBM Usage (GiB)       |
|--------|-----------------------|
| 8      | 27.19 GiB / 31.25 GiB |
| 9      | 27.19 GiB / 31.25 GiB |
| 12     | 25.56 GiB / 31.25 GiB |
| 13     | N/A             |
"""
    rows = parse(live_format)
    assert rows == [(8, 27.19, 31.25), (9, 27.19, 31.25), (12, 25.56, 31.25)]
    # newer bare-number cells (unit in the header)
    assert parse("| 0 | 12.34 |") == [(0, 12.34, 31.246)]
    assert parse("garbage\nno table") == []


def test_trainer_logs_per_host_tpu_telemetry():
    # every host logs (not is_main-gated): the block checks wandb.run directly
    assert 'tpu_telemetry_every' in _TRAIN_SRC
    assert 'f"tpu/host{_hidx}/chip{_cid}_hbm_gib"' in _TRAIN_SRC
    assert 'hasattr(backend, "hbm_per_chip")' in _TRAIN_SRC
    # default off; long-horizon configs opt in
    assert '"tpu_telemetry_every": 0,' in _TRAIN_SRC
    for cfgname in ("stage2_tpu_v6e16_full_v03_mh.yaml", "stage2_tpu_v6e16_full_v03_mh_anneal.yaml"):
        assert "tpu_telemetry_every: 250" in (REPO / "configs" / "tpu" / cfgname).read_text()


# ---------------------------------------------------------------------------
# public-release metrics (Tier A/B/C)
# ---------------------------------------------------------------------------


def test_codebook_entropy_stats():
    import pytest

    if isinstance(sys.modules.get("torch"), MagicMock):
        del sys.modules["torch"]
    torch = pytest.importorskip("torch")  # tensor math; skipped on torch-free CI

    # Factored out to src/evaluation/stats.py (2026-07-15 evals program); the
    # trainer imports it back under the old name -- pin BOTH facts.
    assert "from src.evaluation.stats import codebook_entropy_stats" in _TRAIN_SRC
    from src.evaluation.stats import codebook_entropy_stats as f
    V = 2048
    hist = torch.zeros(3, V)
    hist[0] = 1.0                # uniform -> max entropy = log2(2048) = 11 bits
    hist[1, 7] = 100.0           # one-hot -> 0 bits, active 1/V
    #      hist[2] stays empty  -> zeros
    ent, act = f(hist)
    assert abs(ent[0] - 11.0) < 1e-6 and abs(act[0] - 1.0) < 1e-9
    assert ent[1] == 0.0 and abs(act[1] - 1.0 / V) < 1e-9
    assert ent[2] == 0.0 and act[2] == 0.0


def test_release_metric_wiring():
    # Tier A: counters + sys + ppl + trust-region ratio
    # tokens_seen counts TOKENS (1 text + K codebooks per frame), not frames.
    assert 'tokens_per_frame = 1 + int(cfg["train"].get("num_codebooks", 8))' in _TRAIN_SRC
    assert "tokens_per_step = frame_tokens_per_step * tokens_per_frame" in _TRAIN_SRC
    assert '"train/tokens_seen": float(step) * tokens_per_step' in _TRAIN_SRC
    assert '"train/samples_seen": float(step) * effective_batch' in _TRAIN_SRC
    assert '"train/epoch"' in _TRAIN_SRC
    assert '"sys/resumes": _resume_count' in _TRAIN_SRC
    assert '"resumes": _resume_count' in _TRAIN_SRC  # persisted in extra_state
    assert 'sys/boot_to_first_log_sec' in _TRAIN_SRC
    assert '"val/text_ppl": math.exp(min(_vt, 30.0))' in _TRAIN_SRC
    assert 'f"opt/update_weight_ratio/{gname}"' in _TRAIN_SRC
    # provenance
    assert '"provenance/git_sha": _resolve_build_sha()' in _TRAIN_SRC
    assert '"provenance/data_digest": _read_data_digest(cfg)' in _TRAIN_SRC
    # tpu_topology derived from the real chip count, never a hardcoded slice
    assert 'f"v6e-{backend.world_size()}" if is_tpu' in _TRAIN_SRC
    assert '"tpu_topology": "v6e-8"' not in _TRAIN_SRC
    # Curriculum-independent audio loss: unweighted all-codebook mean from the
    # PRE-mask per-cb CEs -- the public-chart series with no unmask-onset jumps.
    assert '"train/audio_loss_full"' in _TRAIN_SRC
    # Tier B: codebook histogram + exploded list keys
    assert '_codebook_entropy_stats(' in _TRAIN_SRC
    assert '"val/per_codebook_entropy_bits"' in _TRAIN_SRC
    assert 'f"val/per_codebook_active_frac_{i}"' in _TRAIN_SRC
    # Tier C: MFU + PF-days + checkpoint index
    assert 'perf/mfu_est' in _TRAIN_SRC
    assert 'perf/cum_pf_days_est' in _TRAIN_SRC
    assert '"checkpoints/index": wandb.Table(' in _TRAIN_SRC
    # define_metric families
    for fam in ("sys/*", "opt/*", "checkpoints/*", "eval/*"):
        assert f'wandb.define_metric("{fam}", step_metric="global_step")' in _TRAIN_SRC
    # shared-mode bug fix: telemetry rides global_step, never step=
    _tel = _TRAIN_SRC.split("Host-level stats ride along")[1][:1600]
    assert '"global_step": step' in _tel
    assert "_wtel.log(_tel)" in _TRAIN_SRC and "_wtel.log(_tel, step=" not in _TRAIN_SRC


def test_tpu_audio_demo_wiring():
    # static-shape generator exists and never slices with python ints at the
    # frontier (index_select/scatter with runtime index tensors instead)
    assert "def generate_audio_sample_tpu(" in _TRAIN_SRC
    gen_src = _TRAIN_SRC.split("def generate_audio_sample_tpu(")[1].split("\ndef ")[0]
    assert "index_select" in gen_src and ".scatter(" in gen_src
    assert "backend.sync()" in gen_src
    # ALL hosts enter on TPU (no is_main gate on the call), GPU path intact
    assert "if _audio_due and is_tpu:" in _TRAIN_SRC
    assert "generate_audio_sample_tpu(" in _TRAIN_SRC
    assert '"audio_ar_frames": 50,' in _TRAIN_SRC
    # BUILD_SHA stamped into deploy tarballs
    hot = (REPO / "scripts" / "tpu" / "hot_redeploy.sh").read_text()
    assert "git rev-parse HEAD > BUILD_SHA" in hot and "BUILD_SHA" in hot.split("-czf")[1]


def test_hub_publishing_wiring():
    """Async HF-hub artifact publishing: private-by-default, closure-integrated."""
    src_ckpt = (REPO / "src" / "training" / "checkpointing.py").read_text()
    assert "private: bool = True" in src_ckpt
    assert src_ckpt.count("exist_ok=True, private=private") == 2
    assert "def push_files_to_hub(" in src_ckpt
    # the hub push reads the staged LOCAL dir inside the save closure --
    # pushing str(gs://...) post-hoc walks nothing (the old silent no-op)
    assert "hub push failed" in src_ckpt
    # trainer: loud write-access preflight; bundles at best/periodic/final
    assert "push_to_hub enabled but cannot write" in _TRAIN_SRC
    # offline mode must be flipped OFF before hub pushes (build is done by
    # then; the flag would block every push -- caught live by the hub smoke)
    assert 'os.environ.pop("HF_HUB_OFFLINE", None)' in _TRAIN_SRC
    assert "_hf_constants.HF_HUB_OFFLINE = False" in _TRAIN_SRC
    assert '_hub_bundle("best")' in _TRAIN_SRC
    assert _TRAIN_SRC.count('_hub_bundle(f"step-{step}")') == 2  # periodic + final
    # audio + rolling-log artifact pushes
    assert 'f"samples/step_{s:06d}"' in _TRAIN_SRC
    assert '"train_host0_latest.log"' in _TRAIN_SRC
    # long-horizon + anneal configs opt in, PRIVATE
    for cfgname in (
        "stage2_tpu_v6e16_full_v03_mh.yaml",
        "stage2_tpu_v6e16_full_v03_mh_anneal.yaml",
    ):
        t = (REPO / "configs" / "tpu" / cfgname).read_text()
        assert "hub_repo_id: tiny-aya-translate/tr-hi-s2st-v0.3" in t
        assert "hub_private: true" in t


def test_prefetch_direct_primary_warp_fallback():
    """2026-07-15 route fix: direct HF is primary; WARP is retained as fallback."""
    i_direct = _PREFETCH_SRC.index("attempting DIRECT download")
    i_fallback = _PREFETCH_SRC.index("FALLBACK: Cloudflare WARP proxy")
    assert i_direct < i_fallback, "direct attempt must precede the WARP fallback"
    # direct path must fail FAST on a route regression, never hang boot
    assert "timeout 900" in _PREFETCH_SRC
    # fallback still uses the proxy-honoring plain downloader
    assert "HF_HUB_DISABLE_XET=1" in _PREFETCH_SRC
    assert 'ALL_PROXY="$PROXY"' in _PREFETCH_SRC
    # ready-marker fires on BOTH success paths + the warm-cache skip
    assert _PREFETCH_SRC.count("touch /tmp/hf_backbones_ready") == 3


_CKPT_SRC = (REPO / "src" / "training" / "checkpointing.py").read_text()
_REDEPLOY_SRC = (REPO / "scripts" / "tpu" / "_remote_redeploy.sh").read_text()


def test_log_noise_elimination_wiring():
    # (1) torch_xla FSDPv2 full-backward-hook warning filtered at boot
    #     (source: torch_xla/distributed/spmd/xla_sharding.py, fires 1/step;
    #     v0.3-r2's published log was 88% this single line).
    assert 'message=r"Full backward hook is firing' in _TRAIN_SRC
    # (2) peft embedding save intent stated -> no per-save UserWarning
    assert "save_embedding_layers=True" in _CKPT_SRC
    # (3) storage-limit circuit breaker: trip once, announce once, skip rest
    assert "_HUB_PUSH_DISABLED" in _CKPT_SRC
    assert '"storage limit" in str(e).lower()' in _CKPT_SRC
    assert _CKPT_SRC.count("hub and not _HUB_PUSH_DISABLED") == 2
    # (4) published rolling log is deduped before push
    assert "dedupe_repeats" in _TRAIN_SRC
    # (5) boot env hygiene on BOTH launch paths
    for src in (_STARTUP_SRC, _REDEPLOY_SRC):
        assert "HF_HUB_DISABLE_PROGRESS_BARS=1" in src
        assert "TRANSFORMERS_VERBOSITY=error" in src


def test_suite_main_folder_mode_wiring():
    # --main-folder mirrors bundles into main:checkpoints/<label>/ for
    # file-tree discoverability (visitors don't use the branch dropdown);
    # branch mode stays the default (Pythia revision loading).
    src = (REPO / "scripts" / "publish_checkpoint_suite.py").read_text()
    assert '"--main-folder"' in src
    assert 'path_in_repo=f"checkpoints/{branch}"' in src
    assert 'revision="main"' in src
    assert "push_checkpoint_to_hub(" in src  # branch mode still present


def test_dedupe_repeats():
    path = REPO / "src" / "training" / "checkpointing.py"
    spec = importlib.util.spec_from_file_location("ckpt_dedupe", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        import pytest

        pytest.skip("checkpointing needs torch at import time")
    f = mod.dedupe_repeats
    assert f([]) == []
    assert f(["a", "b", "c"]) == ["a", "b", "c"]          # unique -> untouched
    assert f(["w"] * 5) == ["w", "[repeated 5 x]"]
    assert f(["a", "w", "w", "w", "b", "b", "a"]) == [
        "a", "w", "[repeated 3 x]", "b", "[repeated 2 x]", "a",
    ]  # order preserved; non-adjacent repeats NOT merged


def test_audio_full_backfill_derivation():
    # Pure derivation math of the curriculum-independent audio-loss series
    # (scripts/wandb_audio_full_backfill.py; wandb import is lazy in main()).
    path = REPO / "scripts" / "wandb_audio_full_backfill.py"
    spec = importlib.util.spec_from_file_location("wandb_audio_full_backfill", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    K = 4
    rows = [
        # out-of-order steps + one incomplete row (must be skipped)
        {"global_step": 50, **{f"train/per_codebook_loss_{i}": 2.0 for i in range(K)}},
        {"global_step": 25, **{f"train/per_codebook_loss_{i}": 4.0 for i in range(K)}},
        {"global_step": 75, "train/per_codebook_loss_0": 1.0},
        {"global_step": None, **{f"train/per_codebook_loss_{i}": 9.0 for i in range(K)}},
    ]
    out = mod.derive_full_series(rows, K, multipliers=[1.0, 1.0, 2.0, 2.0])
    assert [gs for gs, _, _ in out] == [25, 50]          # sorted, incomplete dropped
    assert out[0][1] == 4.0 and out[1][1] == 2.0          # unweighted mean
    assert out[0][2] == 4.0 and out[1][2] == 2.0          # weighted mean (equal CEs)
    # weighted variant actually weights: CEs [0,0,3,3] with mult [1,1,2,2] -> 2.0
    row = {"global_step": 1, "train/per_codebook_loss_0": 0.0,
           "train/per_codebook_loss_1": 0.0, "train/per_codebook_loss_2": 3.0,
           "train/per_codebook_loss_3": 3.0}
    (_, mean, wmean), = mod.derive_full_series([row], K, [1.0, 1.0, 2.0, 2.0])
    assert mean == 1.5 and wmean == 2.0
    # multiplier-length mismatch refuses
    import pytest
    with pytest.raises(ValueError):
        mod.derive_full_series([row], K, [1.0])


def test_startup_hf_offline_gated_on_prefetch():
    # marker written only by prefetch verification...
    assert 'touch /tmp/hf_backbones_ready' in _PREFETCH_SRC
    assert 'rm -f /tmp/hf_backbones_ready' in _PREFETCH_SRC
    # ...and consumed by BOTH tmux launch branches
    assert '[ -f /tmp/hf_backbones_ready ] && _HF_OFFLINE=1' in _STARTUP_SRC
    assert _STARTUP_SRC.count("HF_HUB_OFFLINE='$_HF_OFFLINE'") == 2


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
