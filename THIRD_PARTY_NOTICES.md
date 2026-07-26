# Third-Party Notices

The TinyAya Stage 2 source code is licensed under Apache-2.0 (see `LICENSE`).
This project, however, **builds on third-party models, datasets, and
libraries that are governed by their own licenses**. Everyone using or
contributing to this project is responsible for complying with the terms
of each component listed below. The Apache-2.0 license of this repository
does **not** relicense any of them.

## Models / weights

| Component | Source | License | What you must know |
|-----------|--------|---------|--------------------|
| **Cohere `tiny-aya` backbone** | CohereLabs / Cohere | **CC-BY-NC-4.0** (non-commercial) | This repo ships **LoRA adapter deltas only**, never the base weights. To run/train you must obtain the base model directly; its **CC-BY-NC-4.0 non-commercial terms are inherited by the released adapter weights**. |
| **Moshi / Mimi (depth decoder + audio codec)** | [kyutai/moshiko](https://huggingface.co/kyutai/moshiko-pytorch-bf16) · [kyutai/mimi](https://huggingface.co/kyutai/mimi) | **CC-BY-4.0** (weights) | Attribution required when redistributing derived weights (the model weights are CC-BY-4.0; Kyutai's Moshi *code* is separately Apache-2.0). |
| **Whisper (alignment, data pipeline)** | OpenAI | MIT | Used for forced alignment in the data pipeline. |

## Datasets

The v0.3 corpus (`tr-hi-mimi-encoded`) is **synthetic**: source text from FLORES /
OPUS-100 / conversational MT, rendered to speech by TTS models, then Mimi-encoded. v0.2
used FLEURS. All sources below apply.

| Dataset / source | Source | License | What you must know |
|---------|--------|---------|--------------------|
| **FLORES** (source text) | Meta / NLLB | **CC BY-SA 4.0** | Attribution + share-alike on derived text. |
| **OPUS-100** (source text) | OPUS project | Per-subcorpus (mixed) | Check the specific subcorpus terms. |
| Conversational MT (source text) | Per-source | Per-source | Inherit each source's terms. |
| **TTS-model outputs** (synthetic speech) | kokoro / XTTS-v2 / chatterbox | Per-model terms | The synthetic audio inherits each TTS model's license/AUP. |
| **FLEURS** (v0.2 only) | Google | **CC BY 4.0** | Attribution required for redistribution of derived data. |
| `tiny-aya-translate/*` encoded datasets | HuggingFace Hub | See each dataset card | Derived from the above; inherit upstream obligations. |

## Libraries (runtime dependencies)

| Library | License |
|---------|---------|
| PyTorch, PyTorch/XLA | BSD-3-Clause |
| HuggingFace Transformers, Tokenizers, Hub, Datasets, Accelerate, PEFT | Apache-2.0 |
| NumPy, SciPy, scikit-learn | BSD-3-Clause |
| librosa, soundfile, soxr | ISC / BSD / LGPL (see each project) |
| Weights & Biases (`wandb`) | MIT |
| `gcsfs`, `sacrebleu`, `pyyaml`, `tqdm` | Apache-2.0 / MIT / BSD |

Library versions are pinned in `pyproject.toml` / `uv.lock`; consult each upstream
project for the authoritative license text.

## Compute acknowledgment

Cloud TPU resources were provided by Google's **TPU Research Cloud (TRC)**.
Research outputs acknowledge the TRC program per its terms (see `NOTICE`).

---

If you believe a component is missing or mis-attributed here, please open an
issue or PR so we can correct it.
