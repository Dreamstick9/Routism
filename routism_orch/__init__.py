"""routism_orch — the standalone learned orchestration engine.

Separate from the `routism` app package. Owns its own model registry
(`orch.yaml`) with a `reserved` flag so coordinator/verifier models are never
offered as app workers. The app wires `safe_plan` in as the fallback until the
head is trained (P5.C).
"""
from __future__ import annotations

from pathlib import Path

from .registry import OrchModel, OrchRegistry
from .engine import OrchestrateResult, OrchestrationEngine
from .orchestrate import orchestrate
from .coordinator import FrozenCoordinator, load_coordinator
from .dataset import build_dataset, load_dataset, tag_match_labeler, PoolModel
from .head import RoutingHead, param_count
from .evolve import train_head, bootstrap_from_labels, separable_cmaes

_REGISTRY_PATH = Path(__file__).resolve().parent / "orch.yaml"


def get_registry() -> OrchRegistry:
    return OrchRegistry.load(_REGISTRY_PATH)


__all__ = [
    "OrchModel",
    "OrchRegistry",
    "get_registry",
    "orchestrate",
    "OrchestrateResult",
    "OrchestrationEngine",
    "FrozenCoordinator",
    "load_coordinator",
    "build_dataset",
    "load_dataset",
    "tag_match_labeler",
    "PoolModel",
    "RoutingHead",
    "param_count",
    "train_head",
    "bootstrap_from_labels",
    "separable_cmaes",
]
