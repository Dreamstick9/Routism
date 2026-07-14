"""P0.C — workflow schema (pydantic).

A workflow is the orchestrator's output: an ordered list of steps, each routed
to one worker with an access_list (which prior outputs it may read). An
access_list entry is either:
- an int: index of a step in the CURRENT query (must be < this step's index), or
- a str "scope:<id>:s:<idx>": a cross-query output from the persistent store.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import memory as memory_mod


class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subtask: str
    worker_id: str
    access_list: list[int | str] = Field(default_factory=list)
    # Engine-assigned role (Trinity/Fugu discipline): thinker|worker|verifier|synthesizer
    role: str = "worker"

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v: str) -> str:
        allowed = {"thinker", "worker", "verifier", "synthesizer"}
        if v not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("access_list")
    @classmethod
    def _valid_refs(cls, v: list[int | str]) -> list[int | str]:
        for ref in v:
            if isinstance(ref, int):
                if ref < 0:
                    raise ValueError(f"access_list int ref must be >= 0, got {ref}")
            elif isinstance(ref, str):
                if memory_mod.parse_scope_ref(ref) is None:
                    raise ValueError(
                        f"access_list str ref must be 'scope:<id>:s:<idx>', got {ref!r}"
                    )
            else:
                raise ValueError(f"access_list entry must be int or scope-ref str, got {ref!r}")
        return v


class Workflow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    steps: list[Step] = Field(min_length=1)

    def validate_against_pool(self, worker_ids: set[str]) -> "Workflow":
        """Ensure every step targets a real worker and access_list is in range.

        Returns self for chaining; raises ValueError on any violation.
        Int refs must point to a PRIOR step (< current index). Scope-ref strings
        are allowed regardless of index (resolved from the persistent store).
        """
        for i, st in enumerate(self.steps):
            if st.worker_id not in worker_ids:
                raise ValueError(
                    f"step {i} references unknown worker_id {st.worker_id!r}; "
                    f"pool has {sorted(worker_ids)}"
                )
            for a in st.access_list:
                if isinstance(a, int) and a >= i:
                    raise ValueError(
                        f"step {i} access_list {st.access_list} points to a "
                        f"current/future step (only prior indices < {i} allowed)"
                    )
        return self
