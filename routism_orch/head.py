"""P5.D — routing head (numpy, ~10K params, no torch).

A TINY MLP that maps the frozen-SLM hidden state h ∈ ℝ¹⁰²⁴ to
(role_logits[3], model_logits[N≤5]). Only THIS is trained (P5.D); the 0.6B
SLM stays frozen. Params ≈ 1024·(3+N) + (3+N) → 6.1K (N=3) … 8.2K (N=5),
well under the ~10K TRINITY budget.

The flat weight vector is partitioned into TWO blocks for block-ε-separable
CMA-ES (TRINITY): block 0 = role weights+bias, block 1 = model weights+bias.
Each block is updated independently (see evolve.py).
"""
from __future__ import annotations

import numpy as np

ROLE_DIM = 3
HID = 1024  # FrozenCoordinator hidden dim (Qwen3-0.6B)


def param_count(n_models: int) -> int:
    """Total trainable params for a head routing among `n_models` workers."""
    return (HID * ROLE_DIM + ROLE_DIM) + (HID * n_models + n_models)


class RoutingHead:
    def __init__(self, n_models: int, weights: np.ndarray | None = None) -> None:
        self.n_models = n_models
        self.P = param_count(n_models)
        if weights is None:
            self.w = np.zeros(self.P, dtype=np.float32)
        else:
            self.w = np.asarray(weights, dtype=np.float32)
            if self.w.shape != (self.P,):
                raise ValueError(f"weights shape {self.w.shape} != ({self.P},)")

    @staticmethod
    def from_flat(w: np.ndarray, n_models: int) -> "RoutingHead":
        return RoutingHead(n_models, weights=w)

    def to_flat(self) -> np.ndarray:
        return self.w.copy()

    def param_blocks(self) -> list[tuple[int, int]]:
        """(lo, hi) index ranges into the flat vector — one block per output
        group, so separable CMA-ES can perturb them independently."""
        p_role = HID * ROLE_DIM + ROLE_DIM
        return [(0, p_role), (p_role, self.P)]

    def forward(self, H: np.ndarray):
        """H: (n,1024) float32 -> (role_logits (n,3), model_logits (n,N))."""
        H = np.asarray(H, dtype=np.float32)
        p_role = HID * ROLE_DIM + ROLE_DIM
        role_w = self.w[: HID * ROLE_DIM].reshape(ROLE_DIM, HID)
        role_b = self.w[HID * ROLE_DIM : p_role]
        model_w = self.w[p_role : p_role + HID * self.n_models].reshape(self.n_models, HID)
        model_b = self.w[p_role + HID * self.n_models :]
        role_logits = H @ role_w.T + role_b
        model_logits = H @ model_w.T + model_b
        return role_logits, model_logits

    def predict(self, h: np.ndarray) -> tuple[int, int]:
        """Single query h (1024,) -> (role_idx, model_idx)."""
        r, m = self.forward(h.reshape(1, -1))
        return int(np.argmax(r)), int(np.argmax(m))
