"""P5.D — separable CMA-ES training of the routing head (pure numpy).

Implements the TRINITY recipe: TRAIN ONLY the ~10K-param head, with a
block-ε-separable CMA-ES against a task-reward. The 0.6B SLM is frozen and
never touched.

Why pure numpy (no pycma):
  - `pycma` is not installed and pip is broken on this box (homebrew shadows
    the interpreter). A self-contained separable CMA-ES keeps `routism_orch`
    dependency-free (numpy is already a base dep) and honors the "separable"
    spec precisely. Swap in pycma later if desired — the optimizer is a
    single function with a stable signature.

Reward (honest bootstrap):
  - Primary reward = validation accuracy of argmax(model_logits) vs the
    ground-truth model label. This is a legitimate, runnable proxy for
    TRINITY's task reward (model solves task). The head learns to READ the
    domain off h, reproducing the tag-match routing.
  - Bootstrapping: we warm-start the mean at a head that already reproduces
    the tag labels (via `bootstrap_from_labels`), so CMA-ES refines rather
    than searches from scratch. Per the P5.C review, we keep the supervised
    warm-start LIGHT and let the search separate models that share a tag.

Block-ε-separable update (per block: independent mean + diagonal sigma).
The blocks are fully DECOUPLED (block-diagonal) — there is no cross-block
ε-correlation; each block's mean/sigma evolve independently. Rank-μ weighted
mean update + a simplified (documented) sigma adaptation. Tractable on CPU in
seconds. If true ε-correlated steps across blocks are wanted later, add a
shared noise term; the current scheme is strictly separable.
"""
from __future__ import annotations

import numpy as np
from typing import Callable

from .head import RoutingHead, ROLE_DIM, HID


def _label_to_idx(labels: list[str], pool: list[str]) -> np.ndarray:
    id_to_idx = {m: i for i, m in enumerate(pool)}
    return np.array([id_to_idx[l] for l in labels], dtype=np.int64)


def bootstrap_from_labels(
    H: np.ndarray, labels: list[str], pool: list[str]
) -> RoutingHead:
    """Least-squares warm start: fit each output unit's linear weights to the
    one-hot label, using a ridged pseudoinverse. This reproduces the tag-match
    routing and gives CMA-ES a sane starting mean."""
    import numpy.linalg as la

    y = _label_to_idx(labels, pool)
    n_models = len(pool)
    Ht = np.asarray(H, dtype=np.float32)
    # ridge pseudoinverse of H for the model head
    HtH = Ht.T @ Ht + 1e-3 * np.eye(HID)
    HtY = Ht.T @ np.eye(n_models)[y]  # (1024, n_models)
    Wm = la.solve(HtH, HtY)  # (1024, n_models)
    bm = np.eye(n_models)[y].mean(axis=0)  # (n_models,)
    # role head: bootstrap to a fixed "worker" bias (role signal is weak in
    # this dataset; default everyone to Worker=idx 1). Keeps it honest.
    Wr = np.zeros((ROLE_DIM, HID), dtype=np.float32)
    br = np.zeros(ROLE_DIM, dtype=np.float32)
    br[1] = 1.0  # Worker
    head = RoutingHead(n_models)
    w = np.concatenate(
        [Wr.reshape(-1), br, Wm.reshape(-1), bm]
    ).astype(np.float32)
    head.w = w
    return head


def _accuracy_of(w: np.ndarray, n_models: int, H: np.ndarray, y_idx: np.ndarray) -> float:
    head = RoutingHead.from_flat(w, n_models)
    _, model_logits = head.forward(H)
    pred = np.argmax(model_logits, axis=1)
    return float(np.mean(pred == y_idx))


def separable_cmaes(
    objective: Callable,  # w -> scalar reward (higher better)
    param_blocks: list[tuple[int, int]],
    x0: np.ndarray,
    *,
    sigma0: float = 0.2,
    generations: int = 40,
    pop: int = 12,
    seed: int = 0,
) -> tuple[np.ndarray, float, list[float]]:
    """Block-ε-separable CMA-ES. Returns (best_w, best_reward, history)."""
    rng = np.random.default_rng(seed)
    means = [x0[lo:hi].astype(np.float64).copy() for (lo, hi) in param_blocks]
    sigmas = [np.full(hi - lo, sigma0) for (lo, hi) in param_blocks]
    best_w = x0.astype(np.float64).copy()
    best_f = objective(best_w)
    history: list[float] = []
    mu = max(1, pop // 2)
    # rank weights (log, normalized)
    raw = np.array([np.log(mu + 0.5) - np.log(i + 1) for i in range(mu)])
    w_rank = raw / raw.sum()

    for _ in range(generations):
        samples = []
        fits = []
        for _ in range(pop):
            x = x0.astype(np.float64).copy()
            for (lo, hi), m, s in zip(param_blocks, means, sigmas):
                x[lo:hi] = m + s * rng.standard_normal(hi - lo)
            samples.append(x)
            fits.append(objective(x))
        order = np.argsort(fits)[::-1]  # maximize
        gen_best = fits[order[0]]
        history.append(gen_best)
        if gen_best > best_f:
            best_f = gen_best
            best_w = samples[order[0]].copy()
        # rank-μ update per block
        for bi, (lo, hi) in enumerate(param_blocks):
            top = np.array([samples[order[k]][lo:hi] for k in range(mu)])
            new_mean = np.average(top, axis=0, weights=w_rank)
            step = new_mean - means[bi]
            # simplified sigma adaptation: grow if step large, shrink if small
            scale = np.exp(0.1 * np.clip(step / (sigmas[bi] + 1e-9), -1, 1))
            sigmas[bi] = np.clip(sigmas[bi] * scale, 1e-3, 1.0)
            means[bi] = new_mean
    return best_w.astype(np.float32), float(best_f), history


def train_head(
    H_train: np.ndarray,
    y_train: list[str],
    pool: list[str],
    *,
    H_val: np.ndarray | None = None,
    y_val: list[str] | None = None,
    generations: int = 40,
    pop: int = 12,
    seed: int = 0,
    sigma0: float = 0.2,
) -> tuple[RoutingHead, dict]:
    """Train the head. Reward = validation (or train) accuracy. Returns the
    trained head + a small metrics dict."""
    n_models = len(pool)
    y_tr_idx = _label_to_idx(y_train, pool)
    Htr = np.asarray(H_train, dtype=np.float32)
    Hv = np.asarray(H_val, dtype=np.float32) if H_val is not None else Htr
    yv_labels = y_val if y_val is not None else y_train
    yv_idx = _label_to_idx(yv_labels, pool)

    base = bootstrap_from_labels(Htr, y_train, pool)
    x0 = base.to_flat().astype(np.float64)
    head_proto = RoutingHead(n_models)
    blocks = head_proto.param_blocks()

    best_w, best_f, history = separable_cmaes(
        lambda w: _accuracy_of(w, n_models, Hv, yv_idx),
        blocks,
        x0,
        sigma0=sigma0,
        generations=generations,
        pop=pop,
        seed=seed,
    )
    trained = RoutingHead.from_flat(best_w, n_models)
    # metrics
    boot_acc = _accuracy_of(base.to_flat(), n_models, Hv, yv_idx)
    final_acc = _accuracy_of(best_w, n_models, Hv, yv_idx)
    majority = float(np.max(np.bincount(yv_idx)) / len(yv_idx))
    return trained, {
        "params": trained.P,
        "bootstrap_acc": boot_acc,
        "trained_acc": final_acc,
        "majority_baseline": majority,
        "beats_baseline": final_acc > majority,
        "history": history,
    }
