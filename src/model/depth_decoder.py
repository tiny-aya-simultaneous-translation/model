"""Depth decoder: creates ``MoshiDepthDecoder`` with optional codebook extension.

WHY THIS EXISTS
---------------
Moshi's depth decoder is the second stage of audio generation: given
the backbone's hidden state at frame ``t``, it autoregressively
produces ``num_codebooks`` audio tokens that together represent one
frame of Mimi-encoded audio. Stage 2 reuses the pretrained Moshi
depth decoder via ``surgery.extract_depth_decoder_state_dict`` and
optionally extends its codebook count with ``extend_weights`` below.

This file is "TPU-adjacent": it constructs a vanilla HuggingFace
module that the composite later patches via ``scan_utils`` for TPU
compile-time and memory wins. There is no ``torch_xla`` import here.
"""

import torch
from transformers.models.moshi.configuration_moshi import MoshiDepthConfig
from transformers.models.moshi.modeling_moshi import MoshiDepthDecoder


def extend_weights(state_dict: dict, orig_q: int, new_q: int) -> dict:
    """Extend depth-decoder weights from ``orig_q`` to ``new_q`` codebooks.

    Parameters
    ----------
    state_dict : dict
        The original depth-decoder state dict.
    orig_q : int
        Original codebook count baked into the pretrained weights.
    new_q : int
        Target codebook count for the composite. May be equal to
        ``orig_q`` (then the state dict is just cloned).

    Returns
    -------
    dict
        A new state dict with FlexibleLinear weights and
        ``embed_tokens`` entries replicated cyclically to the new
        codebook count.

    Notes
    -----
    ``MoshiFlexibleLinear`` weights have shape
    ``[num_codebooks, ...]``. We use cyclic copying so that new
    codebook ``k`` starts from ``k % orig_q`` -- a heuristic that
    keeps initial activations roughly in distribution.
    """
    if orig_q == new_q:
        return {k: v.clone() for k, v in state_dict.items()}

    print(f"  Extending depth decoder: {orig_q} → {new_q} codebooks")
    extended = {}

    for key, weight in state_dict.items():
        if key.startswith("embed_tokens."):
            extended[key] = weight.clone()
            continue

        if weight.dim() >= 2 and weight.shape[0] == orig_q:
            # FlexibleLinear weight — extend first dim
            new_shape = list(weight.shape)
            new_shape[0] = new_q
            new_weight = torch.zeros(new_shape, dtype=weight.dtype)
            new_weight[:orig_q] = weight
            for k in range(orig_q, new_q):
                new_weight[k] = weight[k % orig_q]
            extended[key] = new_weight
        else:
            extended[key] = weight.clone()

    # Extend embed_tokens: orig_q-1 → new_q-1 audio embeddings
    n_orig = orig_q - 1
    n_new = new_q - 1
    for new_idx in range(n_orig, n_new):
        src_key = f"embed_tokens.{new_idx % n_orig}.weight"
        dst_key = f"embed_tokens.{new_idx}.weight"
        extended[dst_key] = state_dict[src_key].clone()

    print(f"  Extended FlexibleLinear weights and embed_tokens ({n_orig} → {n_new})")
    return extended


def _patch_flexible_linear_bmm() -> None:
    """Rewrite ``MoshiFlexibleLinear.forward`` as an equal-batch ``bmm``.

    WHY THIS EXISTS
    ---------------
    Stock transformers (modeling_moshi.py) computes the per-codebook linear as

        torch.matmul(x[:, :, None, :], weight.transpose(1, 2)[None])

    i.e. a batched matmul whose batch dims are ``(B, C)`` on the left and
    ``(1, C)`` on the right. On CUDA the implied ``expand`` of the weight to
    ``(B, C, H, O)`` is a stride-0 view and cuBLAS handles it for free. On
    XLA there are no strides: the expand lowers to a REAL ``broadcast`` and
    the compiler materialises the weight once per token. Observed live on a
    v6e-8 (2026-07-08): ``bf16[64, 8, 1024, 5632]`` = 5.5 GiB for ONE FFN
    weight (batch 4 x depth_chunk 16 tokens), the dominant term of a
    93.94G/31.25G HBM OOM.

    THE FIX
    -------
    Express the same contraction with equal batch dims so XLA lowers it to a
    plain ``dot_general`` with batch dim C and no weight broadcast:

        bmm(x.transpose(0, 1) [C, B, H], w.transpose(1, 2) [C, H, O])

    Numerically identical (same contraction, same dtype); only the lowering
    changes. Applied to the CLASS (idempotent), so every FlexibleLinear in
    the depth decoder -- FFN, in-projections, audio heads -- benefits, on
    GPU and TPU alike (pure torch; no backend seam violation).
    """
    from transformers.models.moshi import modeling_moshi as _mm

    if getattr(_mm.MoshiFlexibleLinear, "_tinyaya_bmm_forward", False):
        return

    def forward(self, x, layer_idx=None):
        # Skip the gather when layer_idx selects every codebook row. The
        # training path always passes the FULL arange(num_codebooks) (the
        # depth sequence positions ARE the codebook indices, and
        # modeling_moshi only ever passes monotonic cache positions), so
        # index_select would be an identity gather -- but on XLA it
        # materialises a fresh copy of the whole weight PER CALL, and each
        # copy is saved for the bmm backward. Observed live on a v6e-8
        # (2026-07-08): thousands of bf16[8,1024,1024] 16M gather copies
        # (19 chunks x 6 layers x 4 attn projs x 8 grad-accum micros)
        # totalling ~50G of an 82.52G/31.25G OOM. Reading self.weight
        # directly shares ONE buffer across all calls.
        w = self.weight
        if layer_idx is not None and layer_idx.numel() != w.shape[0]:
            w = torch.index_select(w, 0, layer_idx)
        if w.shape[0] == 1 and x.shape[1] != 1:
            # Single selected codebook applied to every sequence position
            # (generation path): a plain matmul has no batch-dim mismatch.
            return torch.matmul(x, w[0].transpose(0, 1))
        # x: [B, C, H] -> [C, B, H]; w: [C, O, H] -> [C, H, O]
        return torch.bmm(x.transpose(0, 1), w.transpose(1, 2)).transpose(0, 1)

    _mm.MoshiFlexibleLinear.forward = forward
    _mm.MoshiFlexibleLinear._tinyaya_bmm_forward = True
    print(
        "[depth_decoder] patched MoshiFlexibleLinear.forward -> equal-batch "
        "bmm (avoids XLA materialising the per-token weight broadcast)"
    )


def create_depth_decoder(
    state_dict: dict[str, torch.Tensor],
    num_codebooks: int = 8,
    hidden_size: int = 1024,
    input_size: int = 4096,
    num_layers: int = 6,
    num_heads: int = 16,
    ffn_dim: int = 5632,
    audio_vocab_size: int = 2048,
    text_vocab_size: int = 32000,
    orig_num_codebooks: int = 8,
) -> MoshiDepthDecoder:
    """Create a ``MoshiDepthDecoder`` from a state dict, optionally
    extending its codebook count.

    Parameters
    ----------
    state_dict : dict[str, torch.Tensor]
        Output of :func:`surgery.extract_depth_decoder_state_dict`.
    num_codebooks : int, default 8
        Target codebook count. Must be >= ``orig_num_codebooks``.
    hidden_size, input_size, num_layers, num_heads, ffn_dim, audio_vocab_size,
        text_vocab_size, orig_num_codebooks : int
        Architectural constants matching the pretrained Moshi config.
        Override only when porting to a different Moshi variant.

    Returns
    -------
    MoshiDepthDecoder
        The HF module, weights loaded with ``strict=False``. Missing
        and unexpected key counts are printed for sanity.
    """

    # Extend weights if needed
    if num_codebooks != orig_num_codebooks:
        state_dict = extend_weights(state_dict, orig_num_codebooks, num_codebooks)

    config = MoshiDepthConfig(
        vocab_size=text_vocab_size,
        hidden_size=hidden_size,
        input_size=input_size,
        num_hidden_layers=num_layers,
        num_attention_heads=num_heads,
        num_key_value_heads=num_heads,
        max_position_embeddings=num_codebooks + 1,
        hidden_act="silu",
        head_dim=hidden_size // num_heads,
        ffn_dim=ffn_dim,
        rms_norm_eps=1e-8,
        num_codebooks=num_codebooks,
        audio_vocab_size=audio_vocab_size,
        sliding_window=num_codebooks,
    )

    print(f"Creating MoshiDepthDecoder: {num_codebooks} codebooks, {num_layers} layers")
    _patch_flexible_linear_bmm()
    decoder = MoshiDepthDecoder(config)

    missing, unexpected = decoder.load_state_dict(state_dict, strict=False)
    if missing:
        print(f"  Missing keys: {len(missing)}")
    if unexpected:
        print(f"  Unexpected keys: {len(unexpected)}")

    print(f"  input_projections: {tuple(decoder.input_projections.weight.shape)}")
    print(f"  lm_heads: {tuple(decoder.lm_heads.weight.shape)}")
    print(f"  embed_tokens: {len(decoder.embed_tokens)} audio embeddings")
    print(f"  Total params: {sum(p.numel() for p in decoder.parameters()) / 1e6:.0f}M")

    return decoder
