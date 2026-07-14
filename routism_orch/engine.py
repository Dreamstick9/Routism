"""Routism Orchestration Engine — learned coordinator (TRINITY-style).

P5.A: this is the skeleton. The frozen SLM (Qwen3-0.6B) + trained ~10K head
arrive in P5.B / P5.C. Until then `ready` is False and `orchestrate` degrades
gracefully to the caller-supplied fallback (the app's `safe_plan`), so a weak /
untrained engine can NEVER 500 a request.

Zero dependencies on the `routism` app package — it is a standalone engine that
the app wires a fallback into.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .registry import OrchRegistry
from .head import RoutingHead


@dataclass
class OrchestrateResult:
    """Boundary return value: what the engine produced for one query.

    `workflow` is a `routism.schema.Workflow` (kept as Any here so this package
    stays decoupled from the app). `degraded` is True whenever the engine fell
    back instead of running a learned loop.
    """

    mode: str
    workflow: Any
    used_fallback: bool
    engine_trace: dict = field(default_factory=dict)
    degraded: bool = True

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "used_fallback": self.used_fallback,
            "degraded": self.degraded,
            "engine_trace": self.engine_trace,
        }


class OrchestrationEngine:
    def __init__(self, registry: OrchRegistry | None = None) -> None:
        self.registry = registry or OrchRegistry.load(
            Path(__file__).resolve().parent / "orch.yaml"
        )
        self.head: "RoutingHead | None" = None
        self._coordinator = None  # lazy FrozenCoordinator

    def set_head(self, head: "RoutingHead") -> None:
        """Install a trained routing head (P5.D). Sets `ready=True`."""
        self.head = head

    def _get_coordinator(self):
        if self._coordinator is None:
            from .coordinator import load_coordinator

            self._coordinator = load_coordinator()
        return self._coordinator

    @property
    def ready(self) -> bool:
        """True once a trained head exists (P5.D)."""
        return self.head is not None

    def route(self, query: str, pool: list[str]) -> "OrchestrateResult":
        """Learned route: frozen SLM hidden state -> head -> (role, model).

        `pool` is the list of worker model IDs the app handed us (≤5). The head
        outputs an index into THIS pool, so the engine never invents a worker.
        Falls back gracefully if the head is untrained.
        """
        if not self.ready or self.head is None:
            raise RuntimeError("engine not ready: train/set a head first")
        if not pool:
            raise ValueError("route: empty pool")
        # If the pool size differs from what the head was trained for, the
        # head can't index it safely -> degrade.
        if len(pool) != self.head.n_models:
            raise RuntimeError(
                f"engine head trained for {self.head.n_models} models, "
                f"got pool of {len(pool)}"
            )
        coord = self._get_coordinator()
        h = coord.hidden_state(query, use_cache=True)
        role_idx, model_idx = self.head.predict(h)
        chosen = pool[model_idx]
        coord_model = self.registry.coordinator()
        coord_id = coord_model.id if coord_model is not None else None
        return OrchestrateResult(
            mode="complex",
            workflow=None,
            used_fallback=False,
            degraded=False,
            engine_trace={
                "engine": "routism_orch",
                "head_ready": True,
                "coordinator": coord_id,
                "role": role_idx,
                "model": chosen,
                "pool_size": len(pool),
                "routed_via": "frozen_slm+head",
            },
        )

    def orchestrate(
        self,
        query: str,
        pool: list[str],
        settings: Any,
        *,
        fallback: Callable[[str, Any], tuple[Any, bool]] | None = None,
        max_turns: int = 5,
    ) -> OrchestrateResult:
        """Route one (complex) query through the engine.

        P5.D path: a trained head exists -> route via frozen SLM + head.
        P5.A/C path: head untrained -> delegate to `fallback` (safe_plan).
        """
        if self.ready:
            try:
                return self.route(query, pool)
            except Exception as exc:  # head/coordinator failure -> degrade
                if fallback is None:
                    raise
                wf, used_fb = fallback(query, settings)
                return OrchestrateResult(
                    mode="complex",
                    workflow=wf,
                    used_fallback=True,
                    degraded=True,
                    engine_trace={
                        "engine": "routism_orch",
                        "head_ready": True,
                        "routed_via": "fallback(safe_plan) after head error",
                        "head_error": str(exc),
                    },
                )

        if fallback is None:
            raise RuntimeError(
                "routism_orch engine is not ready (head untrained) and no fallback "
                "was supplied. Wire server.orchestrate() to pass safe_plan."
            )

        wf, used_fallback = fallback(query, settings)
        coord = self.registry.coordinator()
        return OrchestrateResult(
            mode="complex",
            workflow=wf,
            used_fallback=used_fallback,
            degraded=True,
            engine_trace={
                "engine": "routism_orch",
                "head_ready": False,
                "coordinator": coord.id if coord else None,
                "pool_size": len(pool),
                "routed_via": "fallback(safe_plan)",
            },
        )
