"""P5.C — routing dataset harness (standalone; no app imports).

Builds the supervised warm-start dataset that feeds P5.D's CMA-ES head:
    rows of (h: ℝ¹⁰²⁴, y: model_id, domain, query)

Pipeline:
  1. enumerate the app's 1..5 models (passed in as `pool`, NOT imported from
     the app — keeps routism_orch standalone per P5.A).
  2. generate synthetic queries tagged by domain.
  3. use the frozen SLM (`FrozenCoordinator.hidden_state`) to get h (cached).
  4. label each row with the ground-truth model via an injectable `labeler`.

Ground-truth label decision (USER CALL):
  - DEFAULT (in-package, self-contained, non-circular): `tag_match_labeler`
    picks the model whose tags best match the query's domain; falls back to
    the first model. This needs no app import and avoids imitating the weak
    prompted Conductor.
  - OPTION (a) Conductor-distillation: inject `conductor_labeler` from the app
    layer (it would import engine.py). One-line swap — see build_dataset's
    `labeler=` arg. Left to the app; not in-package to preserve isolation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .coordinator import FrozenCoordinator


@dataclass
class PoolModel:
    """Minimal view of an app worker needed for labeling. No app import."""
    id: str
    tags: list[str] = field(default_factory=list)


# Curated synthetic query bank, grouped by domain. Each domain is what we
# expect a model's `tags` to advertise (e.g. "code", "math", "creative").
DOMAIN_QUERIES: dict[str, list[str]] = {
    "code": [
        "Write a Python function to flatten a nested list.",
        "Debug this TypeError: unsupported operand type(s) for +: 'int' and 'str'.",
        "Implement a binary search tree insert in Rust.",
        "Refactor this O(n^2) loop into a vectorized numpy operation.",
        "Explain the difference between a process and a thread.",
        "Write a regex that matches valid IPv4 addresses.",
        "How do I mock an HTTP client in pytest?",
        "Show a SQL query to find duplicate rows by email.",
    ],
    "math": [
        "What is the derivative of x^3 * sin(x)?",
        "Solve the system: 2x + y = 5, x - y = 1.",
        "Prove by induction that the sum of 1..n is n(n+1)/2.",
        "Compute the eigenvalues of [[2, 1], [1, 2]].",
        "What is the probability of drawing two aces from a deck without replacement?",
        "Explain Bayes' theorem with a worked example.",
        "Integrate e^(2x) * cos(x) dx.",
        "What is the time complexity of merge sort and why?",
    ],
    "creative": [
        "Write a short poem about autumn in a quiet village.",
        "Draft a tagline for a sustainable coffee brand.",
        "Continue this story: The lighthouse keeper noticed the light had gone out...",
        "Write a haiku about a rainy Tokyo street.",
        "Compose a witty toast for a best friend's wedding.",
        "Describe a color to someone who has never seen.",
        "Write a dialogue between a clock and a calendar.",
        "Punch up this boring product description with more voice.",
    ],
    "factual": [
        "Who was the first person to walk on the moon?",
        "What year did the Berlin Wall fall?",
        "List the capitals of the G7 countries.",
        "What does HTTP 503 mean?",
        "How many bones are in the adult human body?",
        "What is the difference between mitosis and meiosis?",
        "Name the three branches of the US government.",
        "What causes auroras?",
    ],
    "reasoning": [
        "If all Bloops are Razzies and all Razzies are Lazzies, are all Bloops definitely Lazzies?",
        "A man pushes a car to a hotel and loses his fortune. What happened?",
        "You have 3 switches and a closed room with 3 bulbs. How do you map them with one visit?",
        "Why is 'incorrectly' spelled wrong considered funny?",
        "A farmer has 17 sheep; all but 9 die. How many are left?",
        "Which weighs more: a pound of feathers or a pound of bricks?",
        "If yesterday was two days before Wednesday, what day is tomorrow?",
        "A rooster lays an egg on a slanted roof; which side does it roll?",
    ],
    "summarize": [
        "Summarize the causes of World War I in 3 bullet points.",
        "Condense this paragraph about quantum entanglement into one sentence.",
        "Give me the TL;DR of the Kubernetes vs Docker debate.",
        "Summarize the plot of Macbeth in 4 sentences.",
        "Extract the 3 key takeaways from this meeting transcript.",
        "Boil down this privacy policy to what users should actually care about.",
        "Shorten this email to one line without losing the ask.",
        "Summarize the pros and cons of remote work.",
    ],
}


def tag_match_labeler(domain: str, pool: list[PoolModel]) -> str:
    """Self-contained default labeler (option b): pick the model whose tags
    intersect the query domain; deterministic fallback = first model.

    Non-circular (doesn't imitate the weak Conductor) and needs no app import.
    """
    if not pool:
        raise ValueError("pool is empty")
    best: str | None = None
    for m in pool:
        tags = {t.lower() for t in m.tags}
        if domain.lower() in tags:
            return m.id
        # soft match: any tag shares a token with the domain
        if best is None and any(domain.lower() in t.lower() or t.lower() in domain.lower() for t in tags):
            best = m.id
    return best or pool[0].id


Labeler = Callable[[str, list[PoolModel]], str]


def build_dataset(
    coordinator: FrozenCoordinator,
    pool: list[PoolModel],
    *,
    labeler: Labeler | None = None,
    out_path: str | Path | None = None,
    per_domain: int | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """Generate the routing dataset. Returns rows; optionally writes JSON.

    Each row: {query, domain, h (list[float]), y (model_id)}.
    `h` is the frozen-SLM penultimate hidden state (cached across queries).
    """
    if not pool:
        raise ValueError("pool must contain 1..5 models")
    if len({m.id for m in pool}) != len(pool):
        raise ValueError("duplicate model ids in pool")
    label_fn = labeler or tag_match_labeler

    rows: list[dict] = []
    for domain, queries in DOMAIN_QUERIES.items():
        chosen = queries if per_domain is None else queries[:per_domain]
        for q in chosen:
            h = coordinator.hidden_state(q, use_cache=use_cache)
            y = label_fn(domain, pool)
            rows.append(
                {
                    "query": q,
                    "domain": domain,
                    "h": h.tolist(),
                    "y": y,
                }
            )
    if out_path:
        Path(out_path).write_text(json.dumps(rows, indent=0))
    return rows


def load_dataset(path: str | Path) -> tuple[np.ndarray, list[str], list[dict]]:
    """Load a saved dataset → (H: (n,1024) float32, ys: list[str], meta)."""
    rows = json.loads(Path(path).read_text())
    H = np.array([r["h"] for r in rows], dtype=np.float32)
    ys = [r["y"] for r in rows]
    return H, ys, rows
