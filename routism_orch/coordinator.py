"""P5.B — frozen SLM coordinator + penultimate hidden-state extraction.

Loads Qwen3-0.6B ONCE as a frozen encoder (HF transformers, CPU). For each
query we run a single forward pass and pull the penultimate-token hidden state
from the SECOND-TO-LAST layer — exactly TRINITY's routing signal (ARCHITECTURE
.md §2: Qwen3-0.6B, layer 26, last real token, L2-normalized h ∈ ℝ¹⁰²⁴).

The SLM is frozen (eval() + no grad + deterministic forward). Because the
forward is deterministic for a fixed tokenizer/weights, `query → h` is cached:
each CMA-ES generation (P5.D) only pays SLM forwards ONCE per unique query, then
reuses h. This is the cost-saving trick the design doc calls for.

NOTE: this loads the actual HF model weights (not the Ollama endpoint). The
`orch.yaml` reserved entry is the *registry/identity* contract; the hidden-state
extraction needs the real transformers model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


# Qwen3-0.6B has 28 transformer layers. "penultimate layer" = index 26
# (hidden_states tuple has len = num_layers + 1 incl. the embedding; [-2] is
# the second-to-last transformer block output). Whatever the model, we derive
# it from config so we never hardcode wrong.
_PENULTIMATE_LAYER_OFFSET = 2  # hidden_states[-2]


class FrozenCoordinator:
    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-0.6B",
        device: str = "cpu",
        cache_file: str | Path | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_file = Path(cache_file) if cache_file else None
        self._mem_cache: dict[str, np.ndarray] = {}
        if self.cache_file and self.cache_file.exists():
            try:
                raw = json.loads(self.cache_file.read_text())
                for k, v in raw.items():
                    self._mem_cache[k] = np.asarray(v, dtype=np.float32)
            except Exception:
                self._mem_cache = {}

        # Imported lazily so the rest of routism_orch stays import-light (P5.A
        # gate doesn't need torch).
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, torch_dtype="auto"
        )
        self.model.eval()
        self.model.to(device)
        self.hidden_dim: int = self.model.config.hidden_size
        # number of transformer layers (excluding the embedding at [-1]? hidden
        # states tuple is [emb, layer0, ..., layerN-1]; second-to-last block = [-2])
        self.num_layers: int = self.model.config.num_hidden_layers

    # -- core extraction ---------------------------------------------------
    def _forward_hidden(self, query: str) -> np.ndarray:
        """Single deterministic forward; return L2-normalized penultimate-token
        hidden state from the second-to-last layer as a float32 np.ndarray."""
        import torch

        text = f"QUERY: {query}"
        inputs = self.tokenizer(text, return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.model(**inputs, output_hidden_states=True)
        hidden_states = out.hidden_states  # tuple[len=num_layers+1]
        # second-to-last transformer block output
        second_last = hidden_states[-_PENULTIMATE_LAYER_OFFSET]
        # penultimate TOKEN = last real (non-padding) token position
        seq_len = inputs["input_ids"].shape[1]
        tok_idx = seq_len - 1
        h = second_last[0, tok_idx, :].detach().float().cpu().numpy().astype(np.float32)
        # L2 normalize (TRINITY: h ∈ ℝ^{d} L2-normalized)
        norm = np.linalg.norm(h)
        if norm > 0:
            h = h / norm
        return h

    def hidden_state(self, query: str, *, use_cache: bool = True) -> np.ndarray:
        """Cached `query → h`. Deterministic for a frozen SLM."""
        if use_cache:
            key = self._cache_key(query)
            if key in self._mem_cache:
                return self._mem_cache[key]
        h = self._forward_hidden(query)
        if use_cache:
            key = self._cache_key(query)
            self._mem_cache[key] = h
            self._persist_cache()
        return h

    def _cache_key(self, query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    def _persist_cache(self) -> None:
        if not self.cache_file:
            return
        try:
            self.cache_file.write_text(
                json.dumps({k: v.tolist() for k, v in self._mem_cache.items()})
            )
        except Exception:
            pass

    def clear_cache(self) -> None:
        self._mem_cache = {}
        if self.cache_file and self.cache_file.exists():
            try:
                self.cache_file.unlink()
            except Exception:
                pass


def load_coordinator(
    model_name: str | None = None,
    cache_file: str | Path | None = None,
) -> FrozenCoordinator:
    """Convenience loader. Model name defaults from the engine registry's
    coordinator entry if not given.

    NOTE: the registry's `model` field is the Ollama tag (e.g. `qwen3:0.6b`),
    but the frozen-SLM hidden-state extraction needs the HF transformers repo
    id. We prefer the registry's `hf_model` field (the canonical HF id) and
    fall back to the hardcoded default if absent.
    """
    if model_name is None:
        try:
            from .registry import OrchRegistry

            coord = OrchRegistry.load(
                Path(__file__).resolve().parent / "orch.yaml"
            ).coordinator()
            if coord is not None:
                model_name = getattr(coord, "hf_model", None) or coord.model
        except Exception:
            pass
        if model_name is None:
            model_name = "Qwen/Qwen3-0.6B"
    return FrozenCoordinator(model_name=model_name, cache_file=cache_file)
