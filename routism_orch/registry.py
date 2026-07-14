"""Routism Orchestration Engine — OWN model registry.

Hard separation from the app's user-facing worker pool (routism.yaml):
the engine's thinker/verifier/judge2 brains live ONLY here and are flagged
`reserved: true` so the UI / server never expose them as app workers.

Zero dependencies on the `routism` app package. Importable standalone.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class OrchModel:
    id: str
    role: str  # "coordinator" | "verifier" | "judge2" (Phase 6)
    provider: str
    model: str
    reserved: bool = True
    note: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    thinking: bool = False
    # Canonical HF transformers repo id for the frozen-SLM hidden-state
    # extraction (P5.B). Distinct from `model` (the Ollama tag). Optional for
    # non-coordinator entries.
    hf_model: str | None = None

    @property
    def is_coordinator(self) -> bool:
        return self.role == "coordinator"

    @property
    def is_verifier(self) -> bool:
        return self.role == "verifier"


class OrchRegistry:
    """The engine's private model registry, loaded from `orch.yaml`."""

    def __init__(self, models: list[OrchModel]) -> None:
        self.models = models

    @classmethod
    def load(cls, path: str | Path) -> "OrchRegistry":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"orch registry not found: {p}")
        data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
        models = [OrchModel(**m) for m in data.get("models", [])]
        return cls(models)

    def reserved_ids(self) -> set[str]:
        """Ids of every engine-internal (reserved) model."""
        return {m.id for m in self.models if m.reserved}

    def is_reserved(self, model_id: str) -> bool:
        return model_id in self.reserved_ids()

    def coordinator(self) -> OrchModel | None:
        for m in self.models:
            if m.role == "coordinator":
                return m
        return None

    def verifier(self) -> "OrchModel | None":
        for m in self.models:
            if m.role == "verifier":
                return m
        return None

    def by_role(self, role: str) -> list["OrchModel"]:
        """All engine models with the given `role`. Phase 6 introduces roles
        beyond coordinator/verifier (e.g. `judge2`). Returns a list so future
        roles can have multiple entries without breaking callers.
        """
        return [m for m in self.models if m.role == role]

    def judge2(self) -> "OrchModel | None":
        """The cross-check judge (Phase 6). Returns the first `judge2` entry."""
        js = self.by_role("judge2")
        return js[0] if js else None

    def engine_models(self) -> list["OrchModel"]:
        """All engine-internal (reserved) models, regardless of role."""
        return [m for m in self.models if m.reserved]

    def capability_registry(self) -> dict:
        """Load the capability_registry section from orch.yaml (if present)."""
        # We need to re-read the YAML file to get the capability_registry section.
        try:
            import yaml
            from pathlib import Path
            # Try to find the orch.yaml file
            yaml_path = Path(__file__).parent / "orch.yaml"
            if not yaml_path.exists():
                # Try relative to current working directory
                yaml_path = Path("routism_orch/orch.yaml")
                if not yaml_path.exists():
                    yaml_path = Path(__file__).parent.parent / "routism_orch" / "orch.yaml"
            
            if yaml_path.exists():
                data = yaml.safe_load(yaml_path.read_text()) or {}
                return data.get("capability_registry", {})
        except Exception:
            pass
        return {}

    def as_dict(self) -> dict:
        """Shape the UI consumes to filter engine-reserved models."""
        return {
            "models": [
                {
                    "id": m.id,
                    "role": m.role,
                    "provider": m.provider,
                    "model": m.model,
                    "reserved": m.reserved,
                    "thinking": m.thinking,
                    "note": m.note,
                }
                for m in self.models
            ],
            "reserved_ids": sorted(self.reserved_ids()),
        }
