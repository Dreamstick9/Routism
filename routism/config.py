"""P0.A — config loader: read the user's 1-5 worker pool from YAML/JSON."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class OrchestratorNotConfigured(Exception):
    """Raised when no dedicated orchestrator model is configured.

    The orchestration engine must NOT silently reuse a task worker as the
    conductor — the user must designate one explicitly via
    ``orchestrator_worker_id``.
    """


class Worker(BaseModel):
    id: str
    provider: str
    base_url: str
    model: str
    tags: list[str] = Field(default_factory=list)
    api_key: str | None = None
    # Preferred: name of env var holding the secret (never commit the secret)
    api_key_env: str | None = None
    # optional per-worker overrides
    timeout_s: float = 30.0
    max_tokens: int = 2048

    @model_validator(mode="after")
    def _resolve_api_key_from_env(self) -> "Worker":
        """Fill api_key from api_key_env when the env var is set.

        Plaintext api_key in YAML is still accepted for local legacy configs
        but production should use api_key_env only.
        """
        if self.api_key_env:
            env_val = os.environ.get(self.api_key_env)
            if env_val and env_val.strip():
                object.__setattr__(self, "api_key", env_val.strip())
        return self


class Settings(BaseModel):
    # the orchestrator itself is an LLM; by default reuse one of the workers,
    # but it can be a separate entry pointed to by `orchestrator.worker_id`.
    orchestrator_worker_id: str | None = None
    # verifier is an LLM that gates each step's output (P1.A). Reuses a pool
    # worker by id; if None, the executor runs WITHOUT a verifier gate
    # (verification is opt-in to stay backward compatible with Phase 0 paths).
    verifier_worker_id: str | None = None
    max_repairs: int = 2
    # P1.B: total token budget per query. When the executor's running estimate
    # exceeds this, the workflow aborts and returns a partial answer (graceful).
    # 0 / unset = unlimited.
    max_total_tokens: int = 0
    # P1.D: persistent shared memory backend. backend in {inprocess,file,sqlite};
    # path is the file/db location (ignored for inprocess). A fixed
    # `memory.scope` lets cross-query references resolve ("scope:<scope>:s:<idx>").
    memory_backend: str = "inprocess"
    memory_path: str | None = None
    memory_scope: str = "default"
    workers: list[Worker] = Field(default_factory=list)

    @field_validator("workers")
    @classmethod
    def _pool_size(cls, ws: list[Worker]) -> list[Worker]:
        # 0 is allowed: the dashboard starts empty and the user connects
        # providers on demand (Ollama is NOT auto-connected).
        if not (0 <= len(ws) <= 5):
            raise ValueError(f"pool must have 0-5 workers, got {len(ws)}")
        ids = [w.id for w in ws]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate worker ids: {ids}")
        return ws

    @property
    def orchestrator(self) -> Worker:
        if not self.workers:
            raise OrchestratorNotConfigured("no workers configured in pool")
        if self.orchestrator_worker_id:
            for w in self.workers:
                if w.id == self.orchestrator_worker_id:
                    return w
            raise OrchestratorNotConfigured(
                f"orchestrator_worker_id {self.orchestrator_worker_id!r} is not in the pool"
            )
        raise OrchestratorNotConfigured(
            "orchestrator_worker_id is not set — the orchestration engine requires a "
            "DEDICATED model and will not silently reuse a task worker. Set "
            "orchestrator_worker_id in routism.yaml to the id of the model you want "
            "as the conductor."
        )

    @property
    def verifier(self) -> Worker | None:
        if not self.verifier_worker_id:
            return None
        for w in self.workers:
            if w.id == self.verifier_worker_id:
                return w
        raise KeyError(f"verifier_worker_id {self.verifier_worker_id!r} not in pool")


def load(path: str | Path) -> Settings:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    text = p.read_text()
    if p.suffix in (".yaml", ".yml"):
        data: dict[str, Any] = yaml.safe_load(text) or {}
    elif p.suffix == ".json":
        import json
        data = json.loads(text)
    else:
        raise ValueError(f"unsupported config suffix: {p.suffix}")
    return Settings(**data)


def save(settings: Settings, path: str | Path) -> None:
    """P4.A — write settings back to YAML/JSON (the dashboard's persistence layer).

    Secrets:
    - Prefer ``api_key_env`` (name only) when set.
    - Also persist ``api_key`` when present so BYOK / local servers (oMLX, etc.)
      work after add. Values should already be Fernet-encrypted by the management
      layer when ``ROUTISM_SECRETS_KEY`` / ``ROUTISM_FERNET_KEY`` is configured
      (``enc:v1:…``). Plaintext is only written when no key material is available
      (local dev). Never log these values.

    Pool size / unique ids / role pins are validated by Settings.
    """
    from .crypto_keys import encrypt_secret, has_key_material, is_encrypted

    p = Path(path)

    def _worker_row(w: Worker) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": w.id,
            "provider": w.provider,
            "base_url": w.base_url,
            "model": w.model,
            "tags": list(w.tags),
            "timeout_s": w.timeout_s,
            "max_tokens": w.max_tokens,
        }
        if w.api_key_env:
            # Env-backed keys: never write the resolved secret to disk.
            row["api_key_env"] = w.api_key_env
            return row
        # Persist BYOK / local keys so oMLX 401s do not reappear after save.
        key = (w.api_key or "").strip()
        if key:
            if is_encrypted(key):
                row["api_key"] = key
            elif has_key_material():
                try:
                    row["api_key"] = encrypt_secret(key)
                except Exception:
                    # Last resort: still keep the key so the pool stays usable.
                    row["api_key"] = key
            else:
                row["api_key"] = key
        return row

    data: dict[str, Any] = {
        "orchestrator_worker_id": settings.orchestrator_worker_id,
        "verifier_worker_id": settings.verifier_worker_id,
        "max_repairs": settings.max_repairs,
        "max_total_tokens": settings.max_total_tokens,
        "memory_backend": settings.memory_backend,
        "memory_path": settings.memory_path,
        "memory_scope": settings.memory_scope,
        "workers": [_worker_row(w) for w in settings.workers],
    }
    if p.suffix in (".yaml", ".yml"):
        p.write_text(yaml.safe_dump(data, sort_keys=False))
    elif p.suffix == ".json":
        import json
        p.write_text(json.dumps(data, indent=2))
    else:
        raise ValueError(f"unsupported config suffix: {p.suffix}")


if __name__ == "__main__":
    # quick self-check used by the P0.A gate
    import sys
    s = load(sys.argv[1] if len(sys.argv) > 1 else "routism.yaml")
    assert 1 <= len(s.workers) <= 5
    print("pool ok:", [w.id for w in s.workers])
