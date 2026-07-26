"""Release evaluator: AR generation -> ASR judges -> metrics, per checkpoint.

The end-task eval the proxies can't give: does the GENERATED AUDIO say the
right thing (ASR-chrF++/BLEU/WER vs gold refs, with the GT-audio topline),
does it sound acceptable (MOS deltas vs GT), is it semantically right
(BLASER-2.0 on speech, COMET on transcripts), and how fast is it (RTF/TTFA).
Design + tiering: docs/v0.3-evals-plan.md. GPU strongly recommended
(whisper-large judges); the code itself runs anywhere.

STAGES (resumable; --stages selects):
  generate  AR-generate audio + free-run text for every frozen-subset row;
            writes wav/ + generate.jsonl + code-usage histogram
  asr       whisper judges (vasista22 hi / large-v3 tr) on generated AND
            ground-truth target wavs -> asr.jsonl; optional Gemini referee
  text      corpus metrics per direction vs gold refs (+ topline, AR text)
  mos       DNSMOS + Distill-MOS means and delta vs GT
  semantic  BLASER-2.0 QE/Ref + CometKiwi/COMET-ref     [--semantic_samples]
  judge     Gemini GEMBA adequacy 1-5 + self-consistency [--judge_samples]
  latency   RTF + time-to-first-audible-frame
  report    assemble results.json (+ W&B backfill, + hub push)

Usage (GPU box, full pass):
  uv run python scripts/eval_release.py \
      --checkpoint gs://tinyaya-stage2-eu/ckpts/<run>/step_110000 \
      --subset eval/subsets/v03-val-500.jsonl \
      --val_jsonl /data/splits/val.jsonl --encoded_dir /data/encoded \
      --device cuda --output_dir eval_out/step_110000 \
      --wandb_run cataluna84/tinyaya-stage2-tpu/<run_id>

Checkpoint forms: local dir | gs://... | hub:REPO_ID@step-N (weights-only
hub branches suffice -- the loader reads the bundled peft_adapter config).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import torch  # noqa: E402

# scripts.eval_checkpoint (the canonical loader/AR loop) is imported lazily in
# main(): it drags transformers + the model stack, which the STANDALONE
# semantic venv (--stages semantic,report; see docs/evals-runbook.md) lacks.

STAGES = ("generate", "asr", "text", "mos", "semantic", "judge", "latency", "report")

# direction -> (metric-key suffix, target lang)
_DIR_KEY = {"tr->hi": ("tr2hi", "hi"), "hi->tr": ("hi2tr", "tr")}
MIMI_V = 2048


def _stage_checkpoint(arg: str) -> str:
    """hub:REPO@REV -> local snapshot; local/gs:// pass through.

    Each published revision top-level carries ONLY that checkpoint's own
    weights-only bundle (~3.77 GB: peft_adapter/ + depth_decoder/text_embed/
    heads .pt + metadata.json). But every branch also mirrors the full
    ``checkpoints/`` file-tree-discoverability folder (all ~89 depth_decoders,
    ~51 GB) and demo ``samples/`` wavs + ``logs/`` -- none of which the loader
    reads. Ignore them so staging one checkpoint pulls 3.77 GB, not 51 GB.
    """
    if arg.startswith("hub:"):
        repo, _, rev = arg[4:].partition("@")
        from huggingface_hub import snapshot_download

        path = snapshot_download(
            repo_id=repo, revision=rev or "main",
            token=os.environ.get("HF_TOKEN"),
            ignore_patterns=["checkpoints/*", "samples/*", "logs/*"],
        )
        print(f"[eval] staged {arg} -> {path}", flush=True)
        return path
    return arg


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def _append_jsonl(path: str, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _truncate_sample(sample: dict, n_gen: int) -> dict:
    """View of a dataset sample with the target region capped at n_gen frames."""
    T = sample["source_length"] + n_gen
    out = dict(sample)
    out["text_ids"] = sample["text_ids"][:T]
    out["user_audio_codes"] = sample["user_audio_codes"][:, :T]
    out["model_audio_codes"] = sample["model_audio_codes"][:, :T]
    out["audio_codes"] = sample["audio_codes"][:, :T]
    out["num_frames"] = T
    out["target_length"] = n_gen
    return out


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def stage_generate(args, ec, model, ds, mimi, order, metas) -> None:
    import soundfile as sf

    from src.data.dataset import undo_codebook_delay
    from src.evaluation.stats import new_code_histogram, update_code_histogram

    gen_path = os.path.join(args.output_dir, "generate.jsonl")
    hist_path = os.path.join(args.output_dir, "generate_hist.pt")
    wav_dir = os.path.join(args.output_dir, "wav")
    os.makedirs(wav_dir, exist_ok=True)

    done = {r["base"] for r in _read_jsonl(gen_path)}
    hist = (torch.load(hist_path, weights_only=True)
            if done and os.path.isfile(hist_path)
            else new_code_histogram(8, MIMI_V))

    t0 = time.time()
    for j, (idx, meta) in enumerate(zip(order, metas, strict=True)):
        base = os.path.splitext(os.path.basename(meta["pt_path"]))[0]
        if base in done:
            continue
        sample = ds[idx]
        src_len = sample["source_length"]
        tgt_len = sample["target_length"]

        gen, ar_ids = ec.generate_autoregressive(
            model, sample, args.device, temp=args.ar_temp, top_p=args.ar_top_p,
            free_text=True, return_text=True,
        )
        undelayed = undo_codebook_delay(gen)
        update_code_histogram(hist, undelayed)  # ignores SILENCE(2048) itself

        real = ar_ids < ec._TEXT_SPECIALS_START
        ar_text = model.backbone.tokenizer.decode(ar_ids[real].tolist())

        gt_cb0 = sample["audio_codes"][0, src_len : src_len + gen.shape[1]]
        n = min(len(gt_cb0), gen.shape[1])
        cb0_acc = float((gen[0, :n] == gt_cb0[:n]).float().mean()) if n else None

        paths = {}
        for tag, codes in (
            ("gen", undelayed.clamp(0, MIMI_V - 1)),
            ("gt", sample["audio_codes"][:, src_len : src_len + tgt_len].clamp(0, MIMI_V - 1)),
            ("src", sample["audio_codes"][:, :src_len].clamp(0, MIMI_V - 1)),
        ):
            p = os.path.join(wav_dir, f"{base}.{tag}.wav")
            sf.write(p, mimi.decode(codes).numpy(), 24000)
            paths[f"wav_{tag}"] = p

        _append_jsonl(gen_path, {
            "base": base,
            "direction": meta.get("direction", ""),
            "src_lang": meta.get("src_lang"), "tgt_lang": meta.get("tgt_lang"),
            "src_text": meta.get("src_text"), "tgt_text": meta.get("tgt_text"),
            "ar_text": ar_text, "ar_cb0_acc": cb0_acc,
            "gen_frames": int(gen.shape[1]), **paths,
        })
        torch.save(hist, hist_path)
        if (j + 1) % 10 == 0:
            print(f"[generate] {j + 1}/{len(order)} ({time.time() - t0:.0f}s)",
                  flush=True)
    print(f"[generate] complete: {len(_read_jsonl(gen_path))} rows", flush=True)


def stage_asr(args) -> None:
    from src.evaluation.asr_judge import JUDGE_IDS, WhisperJudge, transcribe_gemini

    gen_rows = _read_jsonl(os.path.join(args.output_dir, "generate.jsonl"))
    asr_path = os.path.join(args.output_dir, "asr.jsonl")
    done = {r["base"] for r in _read_jsonl(asr_path)}
    todo = [r for r in gen_rows if r["base"] not in done]

    for lang in ("hi", "tr"):
        rows = [r for r in todo if r["tgt_lang"] == lang]
        if not rows:
            continue
        judge = WhisperJudge(lang, device=args.device, batch_size=args.asr_batch)
        hyp_gen = judge.transcribe([r["wav_gen"] for r in rows])
        hyp_gt = judge.transcribe([r["wav_gt"] for r in rows])
        for r, hg, ht in zip(rows, hyp_gen, hyp_gt, strict=True):
            _append_jsonl(asr_path, {
                "base": r["base"], "judge": JUDGE_IDS[lang],
                "hyp_gen": hg, "hyp_gt": ht,
            })
        print(f"[asr] {lang}: {len(rows)} pairs via {JUDGE_IDS[lang]}", flush=True)

    if args.gemini_referee > 0:
        from src.evaluation.text_metrics import corpus_scores

        ref_out = {}
        asr_by_base = {r["base"]: r for r in _read_jsonl(asr_path)}
        for lang in ("hi", "tr"):
            rows = [r for r in gen_rows if r["tgt_lang"] == lang][: args.gemini_referee]
            if not rows:
                continue
            gem = transcribe_gemini([r["wav_gen"] for r in rows], lang)
            pairs = [
                (asr_by_base[r["base"]]["hyp_gen"], g)
                for r, g in zip(rows, gem, strict=True)
                if g is not None and r["base"] in asr_by_base
                and asr_by_base[r["base"]]["hyp_gen"]
            ]
            if pairs:
                whisper_hyps, gemini_hyps = (list(t) for t in zip(*pairs, strict=True))
                sc = corpus_scores(whisper_hyps, gemini_hyps, lang, n_bootstrap=1)
                ref_out[lang] = {"n": len(pairs),
                                 "whisper_vs_gemini_chrfpp": sc["chrfpp"]}
        _write_json(os.path.join(args.output_dir, "asr_referee.json"), ref_out)
        print(f"[asr] gemini referee agreement: {ref_out}", flush=True)


def stage_text(args) -> None:
    from src.evaluation.text_metrics import corpus_scores

    gen_rows = _read_jsonl(os.path.join(args.output_dir, "generate.jsonl"))
    asr_by_base = {r["base"]: r for r in
                   _read_jsonl(os.path.join(args.output_dir, "asr.jsonl"))}
    out: dict = {}
    for d, (suffix, lang) in _DIR_KEY.items():
        rows = [r for r in gen_rows if r["direction"] == d and r.get("tgt_text")]
        if not rows:
            continue
        refs = [r["tgt_text"] for r in rows]
        block: dict = {"n": len(rows)}
        withasr = [r for r in rows if r["base"] in asr_by_base]
        if withasr:
            refs_a = [r["tgt_text"] for r in withasr]
            block["asr_gen"] = corpus_scores(
                [asr_by_base[r["base"]]["hyp_gen"] for r in withasr], refs_a,
                lang, n_bootstrap=args.n_bootstrap)
            block["asr_gt_topline"] = corpus_scores(
                [asr_by_base[r["base"]]["hyp_gt"] for r in withasr], refs_a,
                lang, n_bootstrap=args.n_bootstrap)
        block["ar_text"] = corpus_scores(
            [r["ar_text"] for r in rows], refs, lang, n_bootstrap=args.n_bootstrap)
        cb0 = [r["ar_cb0_acc"] for r in rows if r.get("ar_cb0_acc") is not None]
        if cb0:
            block["ar_cb0_acc_mean"] = sum(cb0) / len(cb0)
        out[suffix] = block
    _write_json(os.path.join(args.output_dir, "text.json"), out)
    print(f"[text] {json.dumps({k: {kk: (vv if not isinstance(vv, dict) else vv.get('chrfpp')) for kk, vv in v.items()} for k, v in out.items()}, indent=2)}",
          flush=True)


def stage_mos(args) -> None:
    from src.evaluation.mos import mos_summary

    gen_rows = _read_jsonl(os.path.join(args.output_dir, "generate.jsonl"))
    out = mos_summary([r["wav_gen"] for r in gen_rows],
                      [r["wav_gt"] for r in gen_rows], device=args.device)
    _write_json(os.path.join(args.output_dir, "mos.json"), out)
    print(f"[mos] {json.dumps(out, indent=2)}", flush=True)


def stage_semantic(args) -> None:
    from src.evaluation.semantic import blaser_scores, comet_scores

    gen_rows = _read_jsonl(os.path.join(args.output_dir, "generate.jsonl"))
    asr_by_base = {r["base"]: r for r in
                   _read_jsonl(os.path.join(args.output_dir, "asr.jsonl"))}
    out: dict = {}
    for d, (suffix, lang) in _DIR_KEY.items():
        rows = [r for r in gen_rows if r["direction"] == d][: args.semantic_samples]
        if not rows:
            continue
        src_lang = d.split("->")[0]
        block: dict = {}
        try:
            block["blaser"] = blaser_scores(
                [r["wav_src"] for r in rows], [r["wav_gen"] for r in rows],
                src_lang, lang, ref_texts=[r["tgt_text"] for r in rows],
                device=args.device)
        except Exception as e:  # noqa: BLE001 - heavy optional dep; record + continue
            block["blaser"] = {"skipped": str(e)}
        withasr = [r for r in rows if r["base"] in asr_by_base]
        if withasr:
            srcs = [r["src_text"] for r in withasr]
            hyps = [asr_by_base[r["base"]]["hyp_gen"] for r in withasr]
            refs = [r["tgt_text"] for r in withasr]
            try:
                block["comet_kiwi"] = comet_scores(srcs, hyps, device=args.device)
                block["comet_ref"] = comet_scores(srcs, hyps, refs, device=args.device)
            except Exception as e:  # noqa: BLE001
                block["comet"] = {"skipped": str(e)}
        out[suffix] = block
    _write_json(os.path.join(args.output_dir, "semantic.json"), out)
    print(f"[semantic] written ({list(out)})", flush=True)


def stage_judge(args) -> None:
    from src.evaluation.llm_judge import judge_adequacy

    gen_rows = _read_jsonl(os.path.join(args.output_dir, "generate.jsonl"))
    asr_by_base = {r["base"]: r for r in
                   _read_jsonl(os.path.join(args.output_dir, "asr.jsonl"))}
    out: dict = {}
    for d, (suffix, lang) in _DIR_KEY.items():
        rows = [r for r in gen_rows
                if r["direction"] == d and r["base"] in asr_by_base
                ][: args.judge_samples]
        if not rows:
            continue
        pairs = [(r["src_text"], asr_by_base[r["base"]]["hyp_gen"]) for r in rows]
        out[suffix] = judge_adequacy(pairs, d.split("->")[0], lang)
    _write_json(os.path.join(args.output_dir, "judge.json"), out)
    print(f"[judge] {json.dumps({k: {'mean': v.get('mean'), 'agree': v.get('self_agreement')} for k, v in out.items()})}",
          flush=True)


def stage_latency(args, ec, model, ds, order, metas) -> None:
    from src.evaluation.latency import latency_summary

    picks = list(zip(order, metas, strict=True))[: args.latency_samples]
    runs = []
    for idx, _meta in picks:
        sample = ds[idx]
        frames = min(sample["target_length"], args.latency_frames)
        full = _truncate_sample(sample, frames)
        first = _truncate_sample(sample, 1)
        runs.append(latency_summary(
            lambda s=full: ec.generate_autoregressive(model, s, args.device, temp=0.0),
            lambda s=first: ec.generate_autoregressive(model, s, args.device, temp=0.0),
            frames=frames, device=args.device,
        ))
    out = {
        "per_sample": runs,
        "rtf_mean": sum(r["rtf"] for r in runs) / len(runs),
        "ttfa_s_mean": sum(r["ttfa_s_mean"] for r in runs) / len(runs),
    } if runs else {}
    _write_json(os.path.join(args.output_dir, "latency.json"), out)
    print(f"[latency] rtf={out.get('rtf_mean'):.2f} ttfa={out.get('ttfa_s_mean'):.2f}s"
          if runs else "[latency] no samples", flush=True)


def stage_report(args, step: int, subset_header: dict) -> None:
    from src.evaluation.asr_judge import JUDGE_IDS
    from src.evaluation.report import build_results, wandb_backfill, write_results
    from src.evaluation.stats import codebook_entropy_stats

    res = build_results(
        checkpoint=args.checkpoint, step=step,
        subset_name=subset_header.get("name", "?"),
        subset_digest=subset_header.get("sha256", "?"),
        subset_n=subset_header.get("n", 0),
        decoding={"mode": "greedy" if args.ar_temp <= 0 else "top_p",
                  "temp": args.ar_temp, "top_p": args.ar_top_p},
        judges={"asr_hi": JUDGE_IDS["hi"], "asr_tr": JUDGE_IDS["tr"]},
        seed=1337,
    )
    res["references"] = "synthetic (machine-translated corpus text)"

    metrics: dict = {}
    for name in ("text", "mos", "semantic", "judge", "latency", "asr_referee"):
        p = os.path.join(args.output_dir, f"{name}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                res["metrics"][name] = json.load(f)

    hist_path = os.path.join(args.output_dir, "generate_hist.pt")
    if os.path.isfile(hist_path):
        ent, act = codebook_entropy_stats(torch.load(hist_path, weights_only=True))
        res["metrics"]["gen_codebooks"] = {"entropy_bits": ent, "active_frac": act}
        metrics["eval/gen_codebook_entropy_bits_mean"] = sum(ent) / len(ent)

    text = res["metrics"].get("text", {})
    for suffix, block in text.items():
        for src_key, out_key in (("asr_gen", "asr"), ("asr_gt_topline", "topline_asr"),
                                 ("ar_text", "ar_text")):
            sc = block.get(src_key)
            if sc:
                metrics[f"eval/{out_key}_chrfpp_{suffix}"] = sc["chrfpp"]
                metrics[f"eval/{out_key}_bleu_{suffix}"] = sc["bleu"]
                if "wer" in sc:
                    metrics[f"eval/{out_key}_wer_{suffix}"] = sc["wer"]
    mos = res["metrics"].get("mos", {})
    for pred, block in mos.items():
        if isinstance(block, dict) and "delta_gt" in block:
            metrics[f"eval/mos_{pred}_delta_gt"] = block["delta_gt"]
    sem = res["metrics"].get("semantic", {})
    for suffix, block in sem.items():
        bl = block.get("blaser", {})
        if "blaser_qe_mean" in bl:
            metrics[f"eval/blaser_qe_{suffix}"] = bl["blaser_qe_mean"]
        ck = block.get("comet_kiwi", {})
        if "system_score" in ck:
            metrics[f"eval/comet_kiwi_{suffix}"] = ck["system_score"]
    jd = res["metrics"].get("judge", {})
    for suffix, block in jd.items():
        if block.get("mean") is not None:
            metrics[f"eval/judge_adequacy_{suffix}"] = block["mean"]
    lat = res["metrics"].get("latency", {})
    if "rtf_mean" in lat:
        metrics["eval/rtf"] = lat["rtf_mean"]
        metrics["eval/ttfa_s"] = lat["ttfa_s_mean"]

    res["metrics"]["wandb"] = metrics
    out_path = os.path.join(args.output_dir, "results.json")
    write_results(out_path, res)
    print(f"[report] {out_path}\n{json.dumps(metrics, indent=2)}", flush=True)

    if args.wandb_run:
        wandb_backfill(args.wandb_run, metrics, step)
        print(f"[report] backfilled {len(metrics)} metrics to {args.wandb_run}",
              flush=True)
    if args.hub_repo:
        from src.evaluation.report import push_results_to_hub

        push_results_to_hub([out_path], args.hub_repo,
                            dest_prefix=f"eval/step_{step:06d}",
                            token=os.environ.get("HF_TOKEN"))
        print(f"[report] pushed results.json to {args.hub_repo}", flush=True)


# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True,
                   help="local dir | gs://... | hub:REPO_ID@REVISION")
    p.add_argument("--subset", required=True, help="frozen eval/subsets/*.jsonl")
    p.add_argument("--val_jsonl", required=True)
    p.add_argument("--encoded_dir", required=True)
    p.add_argument("--stages", default="all",
                   help=f"comma list from {','.join(STAGES)} (default all)")
    p.add_argument("--output_dir", default="eval_release_out")
    p.add_argument("--device", default="cuda")
    p.add_argument("--ar_temp", type=float, default=0.0, help="0 = greedy (default)")
    p.add_argument("--ar_top_p", type=float, default=0.9)
    p.add_argument("--limit", type=int, default=0, help="cap subset rows (smoke)")
    p.add_argument("--asr_batch", type=int, default=8)
    p.add_argument("--gemini_referee", type=int, default=0,
                   help="N gen-wavs/direction cross-checked with Gemini ASR")
    p.add_argument("--semantic_samples", type=int, default=200)
    p.add_argument("--judge_samples", type=int, default=50)
    p.add_argument("--latency_samples", type=int, default=3)
    p.add_argument("--latency_frames", type=int, default=100)
    p.add_argument("--n_bootstrap", type=int, default=1000)
    p.add_argument("--wandb_run", default=None, help="entity/project/run_id backfill")
    p.add_argument("--hub_repo", default=None, help="push results.json to this repo")
    p.add_argument("--fp32", action="store_true", help="force fp32 (CPU accuracy)")
    args = p.parse_args()

    stages = STAGES if args.stages == "all" else tuple(args.stages.split(","))
    unknown = set(stages) - set(STAGES)
    if unknown:
        raise SystemExit(f"unknown stages: {sorted(unknown)}")
    os.makedirs(args.output_dir, exist_ok=True)

    from src.evaluation.report import ckpt_step
    from src.evaluation.subset import load_subset

    args.checkpoint = _stage_checkpoint(args.checkpoint)
    sub_rows, subset_header = load_subset(args.subset)
    step = ckpt_step(args.checkpoint)
    print(f"[eval] step={step} subset={subset_header.get('name')} "
          f"sha256={str(subset_header.get('sha256'))[:12]}…", flush=True)

    ec = model = ds = mimi = None
    order: list = []
    metas: list = []
    need_model = bool({"generate", "latency"} & set(stages))
    if need_model:
        import scripts.eval_checkpoint as ec  # heavy: transformers + model stack

        if args.fp32 or args.device == "cpu":
            ec._AC_DTYPE = torch.float32
        model, ds, mimi, _rows = ec.load_model_and_data(
            args.checkpoint, args.val_jsonl, args.encoded_dir, args.device
        )
        by_base = {os.path.basename(r["pt_path"]): i for i, r in enumerate(ds.rows)}
        order, metas, missing = [], [], 0
        for r in sub_rows:
            i = by_base.get(os.path.basename(r["pt_path"]))
            if i is None:
                missing += 1
            else:
                order.append(i)
                metas.append(r)
        if missing:
            raise SystemExit(f"[eval] REFUSING: {missing}/{len(sub_rows)} subset "
                             "rows missing from this corpus")
        if args.limit:
            order, metas = order[: args.limit], metas[: args.limit]

    if "generate" in stages:
        stage_generate(args, ec, model, ds, mimi, order, metas)
    if "asr" in stages:
        stage_asr(args)
    if "text" in stages:
        stage_text(args)
    if "mos" in stages:
        stage_mos(args)
    if "semantic" in stages:
        stage_semantic(args)
    if "judge" in stages:
        stage_judge(args)
    if "latency" in stages:
        stage_latency(args, ec, model, ds, order, metas)
    if "report" in stages:
        stage_report(args, step, subset_header)


if __name__ == "__main__":
    main()
