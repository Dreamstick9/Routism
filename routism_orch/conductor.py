"""Phase 7 — Conductor Mode (Selective Routing + DAG Execution).

This module provides the Conductor planner that decomposes a complex query
into a DAG of subtasks, assigns each subtask to the best-matching worker
based on capability tags, and validates the resulting DAG.

Planner backend (env PLANNER_BACKEND):
  engine (default) — plan_dag via reserved eng-thinker (Ollama OpenAI-compat).
  pool             — plan_dag_with_workers: pick best healthy pool worker tagged
                     reasoning / code / chat; call its OpenAI-compatible
                     /v1/chat/completions for JSON DAG. Same parse +
                     structural_repair + llm_repair pipeline as engine.
                     Callers (server) should fall back to engine on pool failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from routism_orch import engine_client
from routism_orch.engine_client import EngineModelError
from routism_orch.registry import OrchModel, OrchRegistry


# ---------------------------------------------------------------------------
# Planner backend selection
# ---------------------------------------------------------------------------

# PLANNER_BACKEND — product is ENGINE-ONLY for all Conductor planning.
#
# IRON RULE (product): workers are NEVER the engine. Planning / repair /
# synthesize / replan use reserved eng-* models only (orch.yaml).
# PLANNER_BACKEND=pool is intentionally disabled — ignored if set.
# Experimental pool planner code may exist for offline gates only; the live
# server path always uses eng-thinker via engine_client.
def planner_backend() -> str:
    """Always ``engine``. Pool workers must never plan (ENGINE ≠ WORKERS)."""
    v = (os.environ.get("PLANNER_BACKEND") or "engine").strip().lower()
    if v in ("pool", "worker", "workers"):
        # Do not route planning to the user pool — ever.
        return "engine"
    return "engine"


# Preferred capability tags when choosing a pool worker as the planner LLM.
# Lower index = higher preference (first match wins among healthy).
_PLANNER_TAG_PREF: tuple[str, ...] = ("reasoning", "code", "chat")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SampleResult:
    """One k-sample attempt for a subtask (PR-4)."""
    worker_id: str
    answer: str | None = None
    error: str | None = None
    elapsed_ms: float | None = None
    score: float | None = None
    score_reason: str = ""
    sample_index: int = 0

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "answer": self.answer,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "score": self.score,
            "score_reason": self.score_reason,
            "sample_index": self.sample_index,
        }


_VALID_NODE_ROLES = frozenset({"produce", "critique", "verify"})


@dataclass
class Subtask:
    """A single node in the Conductor DAG."""
    id: str
    prompt: str
    tags: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    critical: bool = False  # PR-4: if True and k-sample on, k=2
    role: str = "produce"  # produce|critique|verify
    success_criteria: str = ""
    assigned_worker: str | None = None
    assigned_workers: list[str] = field(default_factory=list)  # full k list
    assignment_reason: str | None = None  # PR-3/4: why workers were picked
    samples: list[SampleResult] = field(default_factory=list)
    result: str | None = None
    selected_worker_id: str | None = None
    error: str | None = None
    elapsed_ms: float | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "tags": self.tags,
            "depends_on": self.depends_on,
            "critical": self.critical,
            "role": self.role,
            "success_criteria": self.success_criteria,
            "assigned_worker": self.assigned_worker,
            "assigned_workers": list(self.assigned_workers),
            "assignment_reason": self.assignment_reason,
            "selected_worker_id": self.selected_worker_id,
            "result": self.result,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "samples": [s.to_dict() for s in self.samples],
        }

@dataclass
class ConductorPlan:
    """Full Conductor execution plan: DAG + layer decomposition."""
    query: str
    subtasks: list["Subtask"] = field(default_factory=list)
    layers: list[list[str]] = field(default_factory=list)  # topological layers (lists of subtask ids)

    def get_subtask(self, id: str) -> Subtask | None:
        for s in self.subtasks:
            if s.id == id:
                return s
        return None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "subtasks": [s.to_dict() for s in self.subtasks],
            "layers": self.layers,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConductorError(Exception):
    """Raised when the Conductor planner or executor fails."""
    def __init__(self, message: str, details: str = ""):
        self.message = message
        self.details = details
        super().__init__(message)


# ---------------------------------------------------------------------------
# Prompts — few-shot structure (engine skill, not keyword hacks)
# ---------------------------------------------------------------------------

# Pass A — structure only (intents); Pass B expands to full work orders.
_CONDUCTOR_SYSTEM = (
    "You are the CONDUCTOR STRUCTURE planner (Pass A) for a multi-model engine.\n"
    "Decompose ANY user request into a dependency-aware DAG of coarse DELIVERABLES.\n"
    "Do NOT special-case demos or any fixed domain. Do NOT write full work-order prose yet.\n"
    "Each node fields: id, intent (one clear deliverable sentence), tags[], depends_on[], "
    "critical (bool), success_criteria (one measurable bar).\n"
    "Also accept legacy field name \"prompt\" as alias for intent.\n"
    "Available capability tags: {capability_registry}\n\n"
    "HARD RULES:\n"
    "1. Prefer 2–4 nodes. Absolute max 5. Fewer rich nodes > many thin ones.\n"
    "2. One node = one coherent DELIVERABLE. Never one node per bullet/list item.\n"
    "3. intent = short deliverable statement for THIS query (not a raw clause cut).\n"
    "4. depends_on only when later needs earlier output. Independent → depends_on [].\n"
    "5. tags from the registry only. Max 3 layers. No cycles.\n"
    "6. Trivial single-intent chat → {{\"dag\": []}}.\n"
    "7. Output ONLY JSON: {{\"dag\":[{{\"id\":\"s1\",\"intent\":\"...\",\"tags\":[\"...\"],"
    "\"depends_on\":[],\"critical\":false,\"success_criteria\":\"...\"}}]}}\n\n"
    "SHAPE (abstract — invent from the real query):\n"
    "A) Multi-part sequential → several nodes with depends_on when needed.\n"
    "B) Two independent asks → two nodes, both depends_on [].\n"
    "C) Single intent → empty dag [].\n"
)

_CONDUCTOR_USER_TEMPLATE = (
    "USER QUERY:\n{query}\n\n"
    "CAPABILITY REGISTRY:\n{capability_registry}\n\n"
    "Pass A only: emit structure JSON (intents + deps + tags + success_criteria). "
    "No full work-order essays. Trivial single intent → {{\"dag\": []}}."
)

_EXPAND_SYSTEM = (
    "You expand ONE orchestration subtask into a full specialist WORK ORDER.\n"
    "Output plain text starting with exactly: ## Work order\n"
    "Include sections: Overall user goal; Your assignment; Mission; Input contract; "
    "Output shape; Success criteria; Non-goals; Rules.\n"
    "Ground everything in the user goal + intent. Do not perform other steps. "
    "Do not invent a different domain. No JSON wrapper."
)

_REPAIR_SYSTEM = (
    "You repair broken orchestration DAG STRUCTURE for ANY domain.\n"
    "Emit FIXED JSON: "
    "{{\"dag\":[{{\"id\",\"intent\",\"tags\",\"depends_on\",\"critical\",\"success_criteria\"}}]}}.\n"
    "(prompt is accepted as alias for intent.)\n"
    "Fix: too many micro-nodes; missing depends_on when later needs earlier; "
    "clones of the full user query; thin/empty intents.\n"
    "Keep 2–4 coarse nodes when multi-step; empty dag if trivial.\n"
    "Output ONLY JSON."
)

_MAX_PLAN_SUBTASKS = 5
# Role ranks for general dependency inference (lower runs earlier).
_ROLE_RANK = {
    "design": 0,
    "implement": 1,
    "test": 2,
    "critique": 2,
    "explain": 3,
    "other": 1,
}
_FRAGMENT_RE = re.compile(
    r"^(test\s*case|case\s*#?\d+|example\s*#?\d+|bullet\s*#?\d+|item\s*#?\d+)[:\s-]+",
    re.I,
)
_REFERS_PRIOR_RE = re.compile(
    r"\b(the (function|code|implementation|api|design|output|result|solution|above)|"
    r"previous|prior|using that|based on|given the|from step|as implemented)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_capability_registry(registry: OrchRegistry) -> str:
    """Format the capability registry for the planner prompt."""
    lines = []
    # Load from orch.yaml capability_registry section
    cap_reg = _load_capability_registry(registry)
    if not cap_reg:
        # Fallback to worker tags from settings
        return "  code, reasoning, math, concise, creative, summarize, explain, fast, chat, reasoning, large_context, multimodal"
    
    for tag, info in cap_reg.items():
        desc = info.get("description", "")
        examples = info.get("example_subtasks", [])
        lines.append(f"  {tag}: {desc} | examples: {', '.join(examples[:3])}")
    return "\n".join(lines)


def _load_capability_registry(registry: OrchRegistry, yaml_path: str = "routism_orch/orch.yaml") -> dict:
    """Load capability_registry directly from orch.yaml file."""
    try:
        import yaml
        from pathlib import Path
        p = Path(yaml_path)
        if p.exists():
            data = yaml.safe_load(p.read_text())
            return data.get("capability_registry", {})
    except Exception:
        pass
    return {}


def _parse_dag_json(text: str) -> list[dict[str, Any]]:
    """Parse the JSON DAG from the planner output.

    Handles fenced code blocks, extra text before/after JSON, and various
    JSON output formats ({"dag": [...]}, [...] bare array, etc.).
    Returns [] (empty DAG) as valid — means "trivial query, use parallel".
    """
    # First try: strict JSON parse of the raw text
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "dag" in data:
            return data["dag"]
        if isinstance(data, list):
            return data
        return []
    except json.JSONDecodeError:
        pass

    # Second try: extract from markdown code fence
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "dag" in data:
                return data["dag"]
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError:
            pass

    # Third try: find the outermost balanced JSON object
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : i + 1])
                        if isinstance(data, dict) and "dag" in data:
                            return data["dag"]
                        if isinstance(data, list):
                            return data
                        return []
                    except json.JSONDecodeError:
                        pass
                    break

    # Last try: find bare array with balanced brackets
    start = text.find("[")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start : i + 1])
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        pass
                    break

    # None worked — but don't crash, return empty DAG which triggers parallel fallback
    return []


def _validate_dag(dag: list[dict[str, Any]], available_tags: set[str]) -> list[Subtask]:
    """Validate DAG structure and return Subtask objects.

    Unknown capability tags do NOT crash validation — they are silently stripped
    so the subtask still works (matched by available tags). This prevents small
    local models from failing an entire orchestration because they hallucinated
    a tag name.

    Dependency resolution is TWO-PASS: deps may reference any id in the DAG,
    not only ones declared earlier in the JSON array (small planners often
    emit deps out of order).
    """
    if not dag:
        return []

    # Pass 1: collect well-formed subtasks (deps not filtered yet).
    # id -> (prompt, tags, deps, critical, role, success_criteria)
    raw: dict[str, tuple[str, list[str], list[str], bool, str, str]] = {}
    for item in dag:
        if not isinstance(item, dict):
            continue
        sid = item.get("id")
        # Pass A uses "intent"; legacy / repair may use "prompt"
        prompt = item.get("prompt") or item.get("intent")
        tags = item.get("tags", [])
        deps = item.get("depends_on", [])
        critical = bool(item.get("critical", False))

        if not sid or not isinstance(sid, str):
            continue  # skip malformed subtasks instead of crashing
        if not prompt or not isinstance(prompt, str):
            continue
        if sid in raw:
            continue
        if not tags or not isinstance(tags, list):
            tags = ["general"]  # assign a safe default tag
        if not isinstance(deps, list):
            deps = []

        # Optional node role (produce|critique|verify) + success criteria.
        role_raw = item.get("role", "produce")
        if isinstance(role_raw, str) and role_raw.strip().lower() in _VALID_NODE_ROLES:
            role = role_raw.strip().lower()
        else:
            role = "produce"
        crit_raw = item.get("success_criteria", "")
        if crit_raw is None:
            success_criteria = ""
        elif isinstance(crit_raw, str):
            success_criteria = crit_raw
        else:
            success_criteria = str(crit_raw)

        # Filter tags: keep only the ones that exist in available_tags.
        # Prefer real capability tags over meta tags (cloud/free/local) when both present.
        _META = {"cloud", "free", "local", "ollama", "paid"}
        capabilityish = [t for t in tags if isinstance(t, str) and t in available_tags and t not in _META]
        valid_tags = capabilityish or [t for t in tags if isinstance(t, str) and t in available_tags]
        if not valid_tags:
            # Prefer a non-meta available tag if possible.
            non_meta = sorted(t for t in available_tags if t not in _META)
            valid_tags = (non_meta or sorted(available_tags))[:1] if available_tags else ["general"]

        raw[sid] = (
            prompt,
            valid_tags,
            [d for d in deps if isinstance(d, str)],
            critical,
            role,
            success_criteria,
        )

    if not raw:
        return []

    # Pass 2: keep only deps that reference real ids in this DAG.
    subtasks: dict[str, Subtask] = {}
    for sid, (prompt, valid_tags, deps, critical, role, success_criteria) in raw.items():
        valid_deps = [d for d in deps if d in raw and d != sid]
        subtasks[sid] = Subtask(
            id=sid,
            prompt=prompt,
            tags=valid_tags,
            depends_on=valid_deps,
            critical=critical,
            role=role,
            success_criteria=success_criteria,
        )

    # Check for cycles using Kahn's algorithm
    in_degree = {sid: 0 for sid in subtasks}
    adj: dict[str, list[str]] = {sid: [] for sid in subtasks}
    for sid, st in subtasks.items():
        for dep in st.depends_on:
            adj[dep].append(sid)
            in_degree[sid] += 1

    queue = [sid for sid, deg in in_degree.items() if deg == 0]
    topo = []
    while queue:
        u = queue.pop(0)
        topo.append(u)
        for v in adj[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    if len(topo) != len(subtasks):
        # Cycle detected — fall back to serial execution (flatten order)
        topo = list(subtasks.keys())
        for sid in topo:
            subtasks[sid].depends_on = []

    result = [subtasks[sid] for sid in topo]
    return result


def _build_layers(subtasks: list[Subtask]) -> list[list[str]]:
    """Build topological layers from validated subtasks.

    Never returns empty layers when subtasks exist (avoids silent no-op runs).
    """
    if not subtasks:
        return []
    ids = {s.id for s in subtasks}
    # Drop dangling deps that block topo (would create phantom in-degree)
    for s in subtasks:
        s.depends_on = [d for d in (s.depends_on or []) if d in ids and d != s.id]

    in_degree = {s.id: 0 for s in subtasks}
    adj: dict[str, list[str]] = {s.id: [] for s in subtasks}
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in adj:
                continue
            adj[dep].append(s.id)
            in_degree[s.id] += 1

    queue = [s.id for s in subtasks if in_degree[s.id] == 0]
    topo: list[str] = []
    while queue:
        u = queue.pop(0)
        topo.append(u)
        for v in adj.get(u, []):
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)

    # Cycle or incomplete topo → flatten to one parallel layer
    if len(topo) != len(subtasks):
        for s in subtasks:
            s.depends_on = []
        return [[s.id for s in subtasks]]

    by_id = {s.id: s for s in subtasks}
    level: dict[str, int] = {}
    for sid in topo:
        st = by_id[sid]
        deps = [d for d in (st.depends_on or []) if d in level]
        if not deps:
            level[sid] = 0
        else:
            level[sid] = max(level[d] for d in deps) + 1

    if not level:
        return [[s.id for s in subtasks]]

    max_level = max(level.values())
    layers: list[list[str]] = [[] for _ in range(max_level + 1)]
    for sid, lvl in level.items():
        layers[lvl].append(sid)
    layers = [L for L in layers if L]
    return layers if layers else [[s.id for s in subtasks]]


# ---------------------------------------------------------------------------
# Structural plan repair (general — not query-string special cases)
# ---------------------------------------------------------------------------


def classify_subtask_role(prompt: str, tags: list[str] | None = None) -> str:
    """Coarse role for dependency inference (content-based, any domain)."""
    t = (prompt or "").lower()
    tagset = {x.lower() for x in (tags or [])}
    if any(k in t for k in ("design", "architect", "spec", "outline", "plan the", "requirements")):
        return "design"
    if any(k in t for k in ("unit test", "pytest", "test case", "test suite", "write tests", "assert")):
        return "test"
    if _FRAGMENT_RE.match(t.strip()) or t.strip().startswith("test case"):
        return "test"
    if any(k in t for k in ("review", "critique", "security risk", "find bugs", "vulnerabilit")):
        return "critique"
    if any(k in t for k in ("explain", "beginner", "eli5", "teach", "summarize how", "bullet point")):
        return "explain"
    if "explain" in tagset and not any(k in t for k in ("implement", "function", "code", "write a")):
        return "explain"
    if any(k in t for k in ("implement", "function", "code", "write a", "build", "develop", "handler", "api")):
        return "implement"
    if "code" in tagset:
        return "implement"
    return "other"


def cap_subtasks(subtasks: list[Subtask], limit: int = _MAX_PLAN_SUBTASKS) -> list[Subtask]:
    """Hard-cap plan size; drop extras (keeps list order)."""
    if len(subtasks) <= limit:
        return subtasks
    kept = subtasks[:limit]
    ids = {s.id for s in kept}
    for s in kept:
        s.depends_on = [d for d in (s.depends_on or []) if d in ids and d != s.id]
    return kept


def merge_fragment_subtasks(subtasks: list[Subtask]) -> list[Subtask]:
    """Merge micro-nodes that are list/test fragments of one deliverable.

    General rules (not tied to a specific demo query):
      * Consecutive 'test case: …' / 'example N: …' fragments → one tests node
      * Consecutive very short same-role prompts → one bundled node
    Preserves non-fragment nodes. Renumbers nothing (ids of survivors stay).
    """
    if len(subtasks) < 2:
        return subtasks

    def _is_frag(s: Subtask) -> bool:
        p = (s.prompt or "").strip()
        if _FRAGMENT_RE.match(p):
            return True
        role = classify_subtask_role(p, s.tags)
        # Short, same-role siblings without deps look like over-split list items
        return role == "test" and len(p) < 80 and not (s.depends_on or [])

    out: list[Subtask] = []
    i = 0
    while i < len(subtasks):
        s = subtasks[i]
        if not _is_frag(s):
            out.append(s)
            i += 1
            continue
        # Collect a run of fragments
        run = [s]
        j = i + 1
        while j < len(subtasks) and _is_frag(subtasks[j]):
            run.append(subtasks[j])
            j += 1
        if len(run) == 1:
            out.append(run[0])
        else:
            lines = [r.prompt.strip() for r in run]
            tags: list[str] = []
            for r in run:
                for t in r.tags or []:
                    if t not in tags:
                        tags.append(t)
            if not tags:
                tags = ["code"]
            out.append(
                Subtask(
                    id=run[0].id,
                    prompt=(
                        "Complete all of the following related items as one deliverable:\n- "
                        + "\n- ".join(lines)
                    ),
                    tags=tags,
                    depends_on=list(run[0].depends_on or []),
                    critical=any(r.critical for r in run),
                )
            )
        i = j

    # Re-point deps that referenced merged-away ids → survivor id in same merge group
    # (simplified: drop dangling deps; infer_dependencies will re-add structure)
    alive = {s.id for s in out}
    for s in out:
        s.depends_on = [d for d in (s.depends_on or []) if d in alive and d != s.id]
    return out


def infer_dependencies(subtasks: list[Subtask]) -> list[Subtask]:
    """Add missing depends_on edges from roles + anaphora (general pipelines).

    Does not force a total order on independent peers (same role, no reference).
    """
    if len(subtasks) < 2:
        return subtasks

    roles = {s.id: classify_subtask_role(s.prompt, s.tags) for s in subtasks}
    by_id = {s.id: s for s in subtasks}

    def _add_dep(later: Subtask, earlier_id: str) -> None:
        if earlier_id == later.id:
            return
        if earlier_id not in by_id:
            return
        deps = list(later.depends_on or [])
        if earlier_id not in deps:
            deps.append(earlier_id)
            later.depends_on = deps

    # Role pipeline: every higher-rank node depends on at least one lower-rank producer
    for later in subtasks:
        r_later = roles[later.id]
        rank_l = _ROLE_RANK.get(r_later, 1)
        # Anaphoric: "the function above" → depend on implement/design nodes
        if _REFERS_PRIOR_RE.search(later.prompt or ""):
            for earlier in subtasks:
                if earlier.id == later.id:
                    continue
                r_e = roles[earlier.id]
                if r_e in ("implement", "design") or _ROLE_RANK.get(r_e, 1) < rank_l:
                    if subtasks.index(earlier) < subtasks.index(later):
                        _add_dep(later, earlier.id)

        if r_later in ("test", "critique", "explain"):
            # Need at least one implement/design ancestor if any exist
            producers = [
                s
                for s in subtasks
                if s.id != later.id and roles[s.id] in ("implement", "design")
            ]
            if producers and not any(
                d in {p.id for p in producers} for d in (later.depends_on or [])
            ):
                # Prefer nearest previous implement, else previous design
                prev = [p for p in producers if subtasks.index(p) < subtasks.index(later)]
                pick = prev[-1] if prev else producers[0]
                _add_dep(later, pick.id)

        if r_later == "implement":
            designs = [
                s
                for s in subtasks
                if s.id != later.id and roles[s.id] == "design"
            ]
            if designs and not any(
                d in {x.id for x in designs} for d in (later.depends_on or [])
            ):
                prev = [d for d in designs if subtasks.index(d) < subtasks.index(later)]
                _add_dep(later, (prev[-1] if prev else designs[0]).id)

    # Distinct role ranks still fully independent → chain by rank (pipeline default)
    if all(not (s.depends_on or []) for s in subtasks) and len(subtasks) >= 2:
        ranks = sorted({_ROLE_RANK.get(roles[s.id], 1) for s in subtasks})
        if len(ranks) >= 2:
            by_rank: dict[int, list[Subtask]] = {}
            for s in subtasks:
                by_rank.setdefault(_ROLE_RANK.get(roles[s.id], 1), []).append(s)
            ordered_ranks = sorted(by_rank.keys())
            for i in range(1, len(ordered_ranks)):
                prev_nodes = by_rank[ordered_ranks[i - 1]]
                for cur in by_rank[ordered_ranks[i]]:
                    _add_dep(cur, prev_nodes[-1].id)

    return subtasks


def plan_structure_issues(subtasks: list[Subtask]) -> list[str]:
    """Detect structural failures a good conductor plan should not have."""
    issues: list[str] = []
    if not subtasks:
        return issues
    if len(subtasks) > _MAX_PLAN_SUBTASKS:
        issues.append("too_many_nodes")
    frag_n = sum(1 for s in subtasks if _FRAGMENT_RE.match((s.prompt or "").strip()))
    if frag_n >= 2:
        issues.append("fragment_over_split")
    roles = [classify_subtask_role(s.prompt, s.tags) for s in subtasks]
    distinct = set(roles)
    no_edges = all(not (s.depends_on or []) for s in subtasks)
    if no_edges and len(subtasks) >= 3 and len(distinct) >= 2:
        issues.append("missing_pipeline_deps")
    if no_edges and len(subtasks) >= 4:
        issues.append("large_flat_parallel")
    # implement + test/explain without edge
    ids_by_role: dict[str, list[str]] = {}
    for s, r in zip(subtasks, roles):
        ids_by_role.setdefault(r, []).append(s.id)
    if ids_by_role.get("implement") and (
        ids_by_role.get("test") or ids_by_role.get("explain")
    ):
        for sid in (ids_by_role.get("test") or []) + (ids_by_role.get("explain") or []):
            st = next(x for x in subtasks if x.id == sid)
            if not any(d in ids_by_role["implement"] for d in (st.depends_on or [])):
                issues.append("test_or_explain_without_implement_dep")
                break
    return issues


def structural_repair(subtasks: list[Subtask]) -> list[Subtask]:
    """Deterministic merge + dependency inference (no query keyword special cases)."""
    subtasks = merge_fragment_subtasks(list(subtasks))
    subtasks = cap_subtasks(subtasks, _MAX_PLAN_SUBTASKS)
    subtasks = infer_dependencies(subtasks)
    return subtasks


def _thin_prompt(prompt: str, query: str) -> bool:
    """True when prompt looks like a raw discourse slice rather than a work order."""
    p = (prompt or "").strip()
    q = (query or "").strip()
    if not p:
        return True
    if p.startswith("Overall user goal:") or p.startswith("## Work order"):
        return False
    # Already has structured sections
    if "Deliverable:" in p or "Output shape:" in p or "Non-goals:" in p:
        return False
    # Short clause / starts with discourse leftovers
    if len(p) < 90:
        return True
    if re.match(
        r"^(then|and then|also|next|finally|after that)\b",
        p,
        re.I,
    ):
        return True
    # Exact (or near) copy of a short substring of the user query
    if q and p.lower() in q.lower() and len(p) < max(120, len(q) * 0.55):
        return True
    return False


def _role_deliverable_hint(content_role: str) -> str:
    """Generic mission line — no domain assumptions (not code/API specific)."""
    return {
        "design": "Produce a concrete plan/spec for this piece: structure, decisions, open questions.",
        "implement": "Produce the full artifact for this scoped piece only (whatever medium the goal requires).",
        "test": "Produce checks/validation that prove the prior artifact works as required.",
        "critique": "Produce a structured review: ranked issues and concrete fixes. Do not replace the whole work.",
        "explain": "Produce a clear explanation for the stated audience. Do not redo other steps' artifacts.",
        "other": "Produce the concrete deliverable described for this step only.",
    }.get(content_role, "Produce the concrete deliverable for this step only.")


def _default_success_criteria(content_role: str, raw: str) -> str:
    base = {
        "design": "Actionable plan with clear decisions and structure",
        "implement": "Complete, self-contained artifact for this scoped piece",
        "test": "Checks covering main paths and important edge cases",
        "critique": "Ranked findings with severity and concrete fixes",
        "explain": "Audience-appropriate explanation that stands alone",
        "other": "Complete, usable output for this step alone",
    }.get(content_role, "Complete, usable output for this step alone")
    if raw and len(raw) < 60:
        return f"{base} ({raw.rstrip('.')})"
    return base


def _default_output_shape(content_role: str) -> str:
    return {
        "design": "Structured sections matching the plan (overview, pieces, decisions, open questions)",
        "implement": "The full artifact plus minimal usage notes; only what this step owns",
        "test": "Labeled cases or checks with expected outcomes",
        "critique": "Bullets: severity, issue, why it matters, fix",
        "explain": "Short sections or bullets for the stated audience",
        "other": "Structured response matching the deliverable in the assignment",
    }.get(content_role, "Structured response matching the deliverable in the assignment")


def craft_work_order(
    query: str,
    *,
    step_id: str,
    step_index: int,
    step_count: int,
    raw_prompt: str,
    content_role: str,
    node_role: str,
    depends_on: list[str] | None,
    success_criteria: str = "",
    tags: list[str] | None = None,
) -> str:
    """Build a full specialist work order from a thin intent + overall goal.

    This is the core upgrade over discourse splits: workers receive a brief with
    goal, deliverable, I/O contracts, success bar, and non-goals — not a clause.
    """
    q = (query or "").strip()
    raw = (raw_prompt or "").strip()
    # Strip prior enrichment wrapper if re-crafting
    if raw.startswith("Overall user goal:") or raw.startswith("## Work order"):
        # Try to recover the assignment body
        m = re.search(
            r"(?:Your assignment[^\n]*:\n|## Assignment\n)([\s\S]+?)(?:\n\n(?:Instructions|## )|\Z)",
            raw,
        )
        if m:
            raw = m.group(1).strip()
    deps = list(depends_on or [])
    tags = list(tags or [])
    criteria = (success_criteria or "").strip() or _default_success_criteria(content_role, raw)
    intent = raw if raw else f"Complete step {step_index} of the overall goal."
    # Normalize discourse leftovers
    intent = re.sub(
        r"^(then|and then|also|next|finally|after that|afterwards)\s+",
        "",
        intent,
        flags=re.I,
    ).strip(" \t\n\r,.;:")
    if intent and not intent.endswith((".", "?", "!", ":")):
        intent = intent + "."

    if deps:
        input_contract = (
            f"You will receive outputs from prior step(s): {', '.join(deps)}. "
            "Treat them as authoritative context. Extend or verify them; do not ignore them. "
            "Do not redo those steps from scratch."
        )
    else:
        input_contract = (
            "No prior-step dependency. Work from the overall goal and this assignment only. "
            "This step may run in parallel with other independent work."
        )

    node_role = (node_role or "produce").strip() or "produce"
    if node_role == "critique":
        mission = "Critique prior outputs; list issues and improvements."
    elif node_role == "verify":
        mission = "Verify prior outputs against requirements; pass/fail with reasons."
    else:
        mission = _role_deliverable_hint(content_role)

    non_goals = {
        "design": "Do not produce the final full artifact of later steps; plan/spec only.",
        "implement": "Do not perform other plan steps; ship only this step's artifact.",
        "test": "Do not redo the primary artifact; only validation/checks for it.",
        "critique": "Do not rewrite the whole solution; review and recommend.",
        "explain": "Do not replace prior artifacts; explain or communicate only.",
        "other": "Do not perform other plan steps; only this deliverable.",
    }.get(content_role, "Do not perform other plan steps; only this deliverable.")

    tag_line = f"Capability tags for matching: {', '.join(tags)}" if tags else ""

    parts = [
        "## Work order",
        f"Step {step_index} of {step_count} · id={step_id} · role={content_role}/{node_role}",
        "",
        "### Overall user goal",
        q or "(see assignment)",
        "",
        "### Your assignment",
        intent,
        "",
        "### Mission",
        mission,
        "",
        "### Input contract",
        input_contract,
        "",
        "### Output shape",
        _default_output_shape(content_role),
        "",
        "### Success criteria",
        criteria,
        "",
        "### Non-goals",
        non_goals,
        "",
        "### Rules",
        "- Produce a complete result for THIS step only.",
        "- Be concrete so downstream specialists can use your output without guessing.",
        "- If context from prior steps is provided in the message, prefer it over inventing alternatives.",
    ]
    if tag_line:
        parts.extend(["", tag_line])
    return "\n".join(parts)


def enrich_subtask_prompts(query: str, subtasks: list[Subtask]) -> list[Subtask]:
    """Rewrite each node into a self-contained work order (not a raw text slice).

    Thin discourse fragments ("Then implement X") become full specialist briefs:
    overall goal, mission, I/O contracts, success criteria, non-goals.
    """
    if not subtasks:
        return subtasks
    n = len(subtasks)
    q = (query or "").strip()
    for i, st in enumerate(subtasks):
        raw = (st.prompt or "").strip()
        # Idempotent: already a crafted work order
        if raw.startswith("## Work order"):
            continue
        content_role = classify_subtask_role(raw, st.tags)
        # If planner already wrote a rich prompt, only light-wrap when needed
        if not _thin_prompt(raw, q) and raw.startswith("Overall user goal:"):
            continue
        if not _thin_prompt(raw, q) and (
            "Deliverable:" in raw or len(raw) >= 160
        ):
            # Rich enough: still attach goal header if missing
            if "Overall user goal" not in raw and "### Overall user goal" not in raw:
                st.prompt = (
                    f"## Work order\n\n### Overall user goal\n{q}\n\n"
                    f"### Your assignment\n{raw}\n\n"
                    f"### Rules\n- Complete THIS step only; do not perform other steps."
                )
            continue
        if not st.success_criteria:
            st.success_criteria = _default_success_criteria(content_role, raw)
        st.prompt = craft_work_order(
            q,
            step_id=st.id,
            step_index=i + 1,
            step_count=n,
            raw_prompt=raw,
            content_role=content_role,
            node_role=(st.role or "produce"),
            depends_on=st.depends_on,
            success_criteria=st.success_criteria,
            tags=st.tags,
        )
    return subtasks


def _subtasks_to_dag_json(subtasks: list[Subtask]) -> list[dict[str, Any]]:
    return [
        {
            "id": s.id,
            "prompt": s.prompt,
            "tags": list(s.tags or []),
            "depends_on": list(s.depends_on or []),
            "role": s.role or "produce",
            "success_criteria": s.success_criteria or "",
        }
        for s in subtasks
    ]


def _repair_messages(
    query: str,
    bad_subtasks: list[Subtask],
) -> list[dict[str, str]]:
    bad_json = json.dumps({"dag": _subtasks_to_dag_json(bad_subtasks)}, indent=2)
    issues = plan_structure_issues(bad_subtasks)
    return [
        {"role": "system", "content": _REPAIR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"USER QUERY:\n{query}\n\n"
                f"ISSUES DETECTED: {', '.join(issues) or 'unspecified quality problems'}\n\n"
                f"BAD PLAN JSON:\n{bad_json}\n\n"
                "Return FIXED JSON only."
            ),
        },
    ]


def _subtasks_from_planner_text(
    text: str,
    available_tags: set[str],
) -> list[Subtask]:
    """Parse + validate planner JSON into Subtask list (may be empty)."""
    dag = _parse_dag_json(text or "")
    if not dag:
        return []
    return _validate_dag(dag, available_tags)


def llm_repair_plan(
    query: str,
    bad_subtasks: list[Subtask],
    *,
    thinker: OrchModel,
    available_tags: set[str],
    base_url: str,
) -> list[Subtask]:
    """Second engine pass: fix structure using eng-thinker (real engine skill)."""
    messages = _repair_messages(query, bad_subtasks)
    try:
        resp = engine_client.call_engine_model(
            thinker,
            messages,
            base_url=base_url,
            temperature=0.0,
            max_tokens=2048,
            timeout=120.0,
            think_override=False,
        )
    except EngineModelError:
        return []
    text = resp.content or resp.thinking or ""
    fixed = _subtasks_from_planner_text(text, available_tags)
    if not fixed:
        return []
    return structural_repair(fixed)


def llm_repair_plan_pool(
    query: str,
    bad_subtasks: list[Subtask],
    *,
    worker: Any,
    available_tags: set[str],
) -> list[Subtask]:
    """Second pass via pool worker (PLANNER_BACKEND=pool path)."""
    messages = _repair_messages(query, bad_subtasks)
    try:
        text = _call_pool_chat_json(worker, messages)
    except ConductorError:
        return []
    fixed = _subtasks_from_planner_text(text, available_tags)
    if not fixed:
        return []
    return structural_repair(fixed)


def expand_work_orders_engine(
    query: str,
    subtasks: list[Subtask],
    *,
    thinker: OrchModel | None = None,
    base_url: str = "http://localhost:11434/v1",
) -> list[Subtask]:
    """Pass B: expand each intent into a full ## Work order.

    Default: deterministic ``craft_work_order`` (fast, full briefs). Optional
    per-node eng-thinker rewrite when ``CONDUCTOR_LLM_EXPAND=1`` (slow).
    Structure (Pass A) remains eng-thinker; workers never expand.
    """
    if not subtasks:
        return subtasks
    n = len(subtasks)
    q = (query or "").strip()
    use_llm = (
        thinker is not None
        and os.environ.get("CONDUCTOR_LLM_EXPAND", "0").strip().lower()
        in ("1", "true", "yes", "on")
    )
    for i, st in enumerate(subtasks):
        raw = (st.prompt or "").strip()
        if raw.startswith("## Work order"):
            continue
        content_role = classify_subtask_role(raw, st.tags)
        if not st.success_criteria:
            st.success_criteria = _default_success_criteria(content_role, raw)
        # Always craft a solid base work order
        crafted = craft_work_order(
            q,
            step_id=st.id,
            step_index=i + 1,
            step_count=n,
            raw_prompt=raw,
            content_role=content_role,
            node_role=(st.role or "produce"),
            depends_on=st.depends_on,
            success_criteria=st.success_criteria,
            tags=st.tags,
        )
        if not use_llm or thinker is None:
            st.prompt = crafted
            continue
        messages = [
            {"role": "system", "content": _EXPAND_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"USER GOAL:\n{q}\n\n"
                    f"STEP id={st.id} index={i + 1}/{n}\n"
                    f"INTENT: {raw}\n"
                    f"TAGS: {', '.join(st.tags or [])}\n"
                    f"DEPENDS_ON: {', '.join(st.depends_on or []) or '(none)'}\n"
                    f"SUCCESS_CRITERIA: {st.success_criteria or '(infer)'}\n"
                    f"ROLE_HINT: {content_role}\n\n"
                    "Write the full work order now."
                ),
            },
        ]
        try:
            text = _call_thinker_json(thinker, messages, base_url=base_url)
            text = (text or "").strip()
            if "## Work order" not in text and text:
                text = "## Work order\n" + text
            st.prompt = text if text and len(text) > 80 else crafted
        except Exception:
            st.prompt = crafted
    return subtasks


def finalize_plan(
    query: str,
    subtasks: list[Subtask],
    *,
    worker_tags: dict[str, list[str]],
    health: dict[str, bool] | None = None,
    force_assign_v2: bool = True,
) -> ConductorPlan:
    """Enrich prompts if needed, assign workers, attach layers.

    Product path always uses assign_v2 when force_assign_v2 (default).
    """
    subtasks = enrich_subtask_prompts(query, list(subtasks))
    layers = _build_layers(subtasks)
    plan = ConductorPlan(query=query, subtasks=subtasks, layers=layers)
    assign_workers_to_plan(
        plan, worker_tags, health=health, force_assign_v2=force_assign_v2
    )
    return plan


# ---------------------------------------------------------------------------
# Pool planner helpers (PLANNER_BACKEND=pool)
# ---------------------------------------------------------------------------


def pick_planner_worker(
    workers: list[Any],
    *,
    health: dict[str, bool] | None = None,
) -> Any | None:
    """Pick best healthy pool worker for planning.

    Preference order among healthy workers that carry preferred tags:
    ``reasoning`` > ``code`` > ``chat``. Among equals, stable by worker id.
    If none have preferred tags, fall back to any healthy worker. If health
    map marks all unhealthy, treat all as eligible (same spirit as assign v2).
    """
    if not workers:
        return None
    by_id = {getattr(w, "id", None): w for w in workers if getattr(w, "id", None)}
    if not by_id:
        return None
    health = health or {}
    healthy_ids = [wid for wid in by_id if health.get(wid, True)]
    if not healthy_ids:
        healthy_ids = list(by_id.keys())

    def _pref_rank(wid: str) -> tuple:
        tags = {t.lower() for t in (getattr(by_id[wid], "tags", None) or [])}
        # Lower rank = better. Missing preferred tags → large rank.
        rank = len(_PLANNER_TAG_PREF)
        for i, pref in enumerate(_PLANNER_TAG_PREF):
            if pref in tags:
                rank = i
                break
        return (rank, wid)

    best_id = min(healthy_ids, key=_pref_rank)
    return by_id[best_id]


def _chat_completions_url(base_url: str) -> str:
    """OpenAI-compatible chat completions URL (mirrors routism.worker)."""
    url = (base_url or "").rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/chat/completions"


def _resolve_worker_api_key(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        from routism.crypto_keys import resolve_api_key

        return resolve_api_key(raw) or raw
    except Exception:
        return raw


def _call_pool_chat_json(
    worker: Any,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    timeout: float = 120.0,
) -> str:
    """Call a pool worker's OpenAI-compatible chat endpoint; return assistant text.

    Raises ConductorError on transport / HTTP / shape failures.
    """
    base = getattr(worker, "base_url", None) or ""
    model = getattr(worker, "model", None) or ""
    wid = getattr(worker, "id", "?")
    if not base or not model:
        raise ConductorError(f"Pool planner worker {wid!r} missing base_url or model")

    url = _chat_completions_url(base)
    headers: dict[str, str] = {"content-type": "application/json"}
    key = _resolve_worker_api_key(getattr(worker, "api_key", None))
    if key:
        headers["Authorization"] = f"Bearer {key}"

    # Prefer worker timeout when present, but planning needs a longer floor.
    w_timeout = getattr(worker, "timeout_s", None)
    if w_timeout is not None:
        try:
            timeout = max(float(w_timeout), 30.0)
        except (TypeError, ValueError):
            pass
    w_max = getattr(worker, "max_tokens", None)
    if w_max is not None:
        try:
            max_tokens = max(int(w_max), 512)
        except (TypeError, ValueError):
            pass

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        msg = data["choices"][0]["message"]
        text = msg.get("content") or msg.get("reasoning") or ""
        if not isinstance(text, str):
            text = str(text)
        return text
    except httpx.TimeoutException as e:
        raise ConductorError(f"Pool planner timeout on {wid}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise ConductorError(
            f"Pool planner HTTP {e.response.status_code} on {wid}: {e.response.text[:200]}"
        ) from e
    except httpx.HTTPError as e:
        raise ConductorError(f"Pool planner transport error on {wid}: {e}") from e
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ConductorError(f"Pool planner bad response from {wid}: {e!r}") from e


def _worker_tags_from_workers(workers: list[Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for w in workers:
        wid = getattr(w, "id", None)
        if not wid:
            continue
        out[wid] = list(getattr(w, "tags", None) or [])
    return out


def _planner_messages(query: str, registry: OrchRegistry) -> list[dict[str, str]]:
    cap_text = _format_capability_registry(registry)
    user_prompt = _CONDUCTOR_USER_TEMPLATE.format(
        query=query, capability_registry=cap_text
    )
    return [
        {
            "role": "system",
            "content": _CONDUCTOR_SYSTEM.format(capability_registry=cap_text),
        },
        {"role": "user", "content": user_prompt},
    ]


def _available_tags_from_worker_tags(worker_tags: dict[str, list[str]]) -> set[str]:
    available: set[str] = set()
    for tags in worker_tags.values():
        available.update(tags)
    return available


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _call_thinker_json(
    thinker: OrchModel,
    messages: list[dict],
    *,
    base_url: str,
) -> str:
    resp = engine_client.call_engine_model(
        thinker,
        messages,
        base_url=base_url,
        temperature=0.0,
        max_tokens=2048,
        timeout=120.0,
        think_override=False,
    )
    return resp.content or resp.thinking or ""


async def plan_dag(
    query: str,
    *,
    registry: OrchRegistry,
    worker_tags: dict[str, list[str]],
    base_url: str = "http://localhost:11434/v1",
    health: dict[str, bool] | None = None,
) -> ConductorPlan:
    """Plan a Conductor DAG via eng-thinker only (two-pass).

    Pipeline:
      1. Pass A: eng-thinker structure JSON (intents, deps, tags, criteria)
      2. validate + structural_repair; optional structure repair pass
      3. Pass B: eng-thinker expands each node to ## Work order
      4. assign_v2 + layers
      5. empty structure → heuristic / single_task + expand
    """
    thinker = registry.coordinator()
    if not thinker:
        raise ConductorError("No coordinator/thinker model in registry")

    available_tags = _available_tags_from_worker_tags(worker_tags)
    if not available_tags:
        raise ConductorError("No worker capability tags available")

    messages = _planner_messages(query, registry)
    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(
            None,
            lambda: _call_thinker_json(thinker, messages, base_url=base_url),
        )
    except EngineModelError as e:
        raise ConductorError(f"Engine call failed: {e}") from e

    subtasks = _subtasks_from_planner_text(text, available_tags)
    if not subtasks:
        plan = heuristic_plan(query, worker_tags, health=health)
        if plan.subtasks:
            # heuristic already finalize+enrich; ensure work orders
            plan.subtasks = await loop.run_in_executor(
                None,
                lambda: expand_work_orders_engine(
                    query, plan.subtasks, thinker=thinker, base_url=base_url
                ),
            )
            # re-assign after expand
            assign_workers_to_plan(
                plan, worker_tags, health=health, force_assign_v2=True
            )
            return plan
        # single-task whole query
        plan = single_task_plan(query, worker_tags, health=health)
        plan.subtasks = await loop.run_in_executor(
            None,
            lambda: expand_work_orders_engine(
                query, plan.subtasks, thinker=thinker, base_url=base_url
            ),
        )
        assign_workers_to_plan(plan, worker_tags, health=health, force_assign_v2=True)
        return plan

    subtasks = structural_repair(subtasks)

    if plan_structure_issues(subtasks):
        repaired = await loop.run_in_executor(
            None,
            lambda st=subtasks: llm_repair_plan(
                query,
                st,
                thinker=thinker,
                available_tags=available_tags,
                base_url=base_url,
            ),
        )
        if repaired:
            subtasks = repaired

    if not subtasks:
        plan = single_task_plan(query, worker_tags, health=health)
        plan.subtasks = await loop.run_in_executor(
            None,
            lambda: expand_work_orders_engine(
                query, plan.subtasks, thinker=thinker, base_url=base_url
            ),
        )
        assign_workers_to_plan(plan, worker_tags, health=health, force_assign_v2=True)
        return plan

    # Pass B — expand intents to full work orders (engine only)
    subtasks = await loop.run_in_executor(
        None,
        lambda: expand_work_orders_engine(
            query, subtasks, thinker=thinker, base_url=base_url
        ),
    )
    return finalize_plan(
        query, subtasks, worker_tags=worker_tags, health=health, force_assign_v2=True
    )


async def plan_dag_with_workers(
    query: str,
    *,
    registry: OrchRegistry,
    workers: list[Any],
    worker_tags: dict[str, list[str]] | None = None,
    health: dict[str, bool] | None = None,
    planner_worker: Any | None = None,
) -> ConductorPlan:
    """Plan a Conductor DAG using a pool worker as the planner LLM.

    Used when ``PLANNER_BACKEND=pool``. Picks the best healthy worker with tags
    ``reasoning`` / ``code`` / ``chat`` (unless ``planner_worker`` is given),
    calls OpenAI-compatible chat for JSON DAG, then applies the same
    ``_parse_dag_json`` → ``structural_repair`` → ``llm_repair`` pipeline as
    :func:`plan_dag`.

    Raises ConductorError if no worker is usable or the chat call fails —
    callers should fall back to engine ``plan_dag``.
    """
    if worker_tags is None:
        worker_tags = _worker_tags_from_workers(workers)
    available_tags = _available_tags_from_worker_tags(worker_tags)
    if not available_tags:
        raise ConductorError("No worker capability tags available")

    picker = planner_worker or pick_planner_worker(workers, health=health)
    if picker is None:
        raise ConductorError("No pool worker available for PLANNER_BACKEND=pool")

    messages = _planner_messages(query, registry)
    loop = asyncio.get_event_loop()
    try:
        text = await loop.run_in_executor(
            None,
            lambda: _call_pool_chat_json(picker, messages),
        )
    except ConductorError:
        raise
    except Exception as e:
        raise ConductorError(f"Pool planner call failed: {e}") from e

    subtasks = _subtasks_from_planner_text(text, available_tags)
    if not subtasks:
        return heuristic_plan(query, worker_tags, health=health)

    subtasks = structural_repair(subtasks)

    if plan_structure_issues(subtasks):
        repaired = await loop.run_in_executor(
            None,
            lambda st=subtasks: llm_repair_plan_pool(
                query,
                st,
                worker=picker,
                available_tags=available_tags,
            ),
        )
        if repaired:
            subtasks = repaired

    if not subtasks:
        return heuristic_plan(query, worker_tags, health=health)

    return finalize_plan(query, subtasks, worker_tags=worker_tags, health=health)


# ---------------------------------------------------------------------------
# Capability matching
# ---------------------------------------------------------------------------


# Meta tags that describe hosting, not capability — optional soft bonus only.
_META_TAGS = frozenset({"cloud", "free", "local", "ollama", "paid", "fast"})


def match_subtask_to_worker(
    subtask: Subtask,
    worker_tags: dict[str, list[str]],
    *,
    usage: dict[str, int] | None = None,
) -> str | None:
    """Pick a worker for a subtask (legacy least-used + soft tags).

    PRIMARY rule: round-robin / least-used across the whole pool.
    Tags are a soft bonus only — they NEVER exclude a worker. A powerful
    model with sparse tags (e.g. only code/reasoning) still gets work.
    """
    if not worker_tags:
        return None
    usage = usage or {}
    stags = set(subtask.tags or ()) - _META_TAGS

    def _key(worker_id: str) -> tuple:
        wtags = set(worker_tags.get(worker_id) or ()) - _META_TAGS
        soft_bonus = len(stags & wtags)  # 0 is fine — never disqualifies
        # least-used first, then soft tag bonus, then stable id
        return (usage.get(worker_id, 0), -soft_bonus, worker_id)

    return min(worker_tags.keys(), key=_key)


def apply_critical_validation(plan: ConductorPlan, *, k_critical: int = 2) -> ConductorPlan:
    """PR-4 plan validation for critical flags (mutates plan).

    1. If sum(critical) > 2, keep first two in topo order, clear the rest.
    2. If plan has ≥2 layers and zero critical, mark last topo subtask critical.
    """
    if not plan.subtasks:
        return plan
    # Topo order = flatten layers if present, else plan.subtasks order
    if plan.layers:
        topo: list[str] = [sid for layer in plan.layers for sid in layer]
    else:
        topo = [s.id for s in plan.subtasks]
    by_id = {s.id: s for s in plan.subtasks}

    critical_ids = [sid for sid in topo if by_id.get(sid) and by_id[sid].critical]
    if len(critical_ids) > 2:
        keep = set(critical_ids[:2])
        for sid in critical_ids:
            if sid not in keep and sid in by_id:
                by_id[sid].critical = False

    if len(plan.layers) >= 2 and not any(s.critical for s in plan.subtasks):
        last = topo[-1] if topo else None
        if last and last in by_id:
            by_id[last].critical = True

    # Max 5 subtasks / 3 layers already soft-enforced by planner; leave as-is.
    _ = k_critical
    return plan


def _prefer_distinct_verify_workers(
    plan: ConductorPlan,
    worker_tags: dict[str, list[str]],
) -> None:
    """Prefer verify-role nodes on a different worker than produce deps (pool≥2)."""
    workers = list(worker_tags.keys())
    if len(workers) < 2 or not plan.subtasks:
        return
    by_id = {s.id: s for s in plan.subtasks}

    for st in plan.subtasks:
        if (st.role or "produce") != "verify":
            continue
        produce_workers: set[str] = set()
        for dep_id in st.depends_on or []:
            dep = by_id.get(dep_id)
            if not dep:
                continue
            if (dep.role or "produce") in ("produce", "critique"):
                if dep.assigned_worker:
                    produce_workers.add(dep.assigned_worker)
                for w in dep.assigned_workers or []:
                    if w:
                        produce_workers.add(w)
        # Fallback: any produce node in the plan when deps lack assignments
        if not produce_workers:
            for other in plan.subtasks:
                if other.id == st.id:
                    continue
                if (other.role or "produce") == "produce" and other.assigned_worker:
                    produce_workers.add(other.assigned_worker)

        current = st.assigned_worker
        if current and current not in produce_workers:
            continue  # already distinct

        stags = set(st.tags or ())
        alternatives = [w for w in workers if w not in produce_workers]
        if not alternatives:
            alternatives = [w for w in workers if w != current]
        if not alternatives:
            continue
        alternatives.sort(
            key=lambda w: (
                -len(stags & set(worker_tags.get(w) or ())),
                w,
            )
        )
        pick = alternatives[0]
        st.assigned_worker = pick
        rest = [w for w in (st.assigned_workers or []) if w != pick]
        st.assigned_workers = [pick] + rest
        reason = st.assignment_reason or ""
        st.assignment_reason = (
            f"{reason}+verify_distinct" if reason else "verify_distinct"
        )


def assign_workers_to_plan(
    plan: ConductorPlan,
    worker_tags: dict[str, list[str]],
    *,
    health: dict[str, bool] | None = None,
    force_assign_v2: bool = True,
    exclude: dict[str, set[str]] | None = None,
) -> ConductorPlan:
    """Assign workers to each subtask.

    Product path (force_assign_v2=True): always unit-normalized assign_v2 +
    k-sample when critical. Never silent legacy_least_used on Conductor.

    ``exclude``: optional map subtask_id → worker ids to skip (reassign).
    """
    from routism_orch.assign import (
        assign_k,
        assign_v2_enabled,
        get_worker_stats,
        k_sample_enabled,
    )

    # Force code/test produce steps critical so reassign+k-sample fire on fail
    for st in plan.subtasks:
        role = (
            str(getattr(st, "content_role", None) or "")
            + " "
            + str(getattr(st, "node_role", None) or "")
        ).lower()
        prompt_l = (st.prompt or "").lower()
        is_codeish = (
            "test" in role
            or "implement" in role
            or "code" in role
            or "unit test" in prompt_l
            or "implement" in prompt_l[:240]
            or "handler" in prompt_l[:240]
        )
        if is_codeish:
            st.critical = True
            # Ensure capability tags include code so free-tier chat models
            # without strong code affinity lose to code-tagged workers.
            st.tags = list(dict.fromkeys(list(st.tags or []) + ["code", "reasoning"]))
    apply_critical_validation(plan)

    usage: dict[str, int] = {wid: 0 for wid in worker_tags}
    # Product: force v2 unless explicitly disabled AND force_assign_v2 is False
    use_v2 = True if force_assign_v2 else assign_v2_enabled()
    use_k = k_sample_enabled()
    stats = get_worker_stats() if use_v2 else None
    plan_size = max(1, len(plan.subtasks))
    exclude = exclude or {}

    for subtask in plan.subtasks:
        k = 2 if (use_k and subtask.critical) else 1
        tags_map = dict(worker_tags)
        ban = set(exclude.get(subtask.id) or set())
        # For unit-test steps, prefer workers with explicit code tags when pool has them
        pl = (subtask.prompt or "").lower()
        is_test_step = "test" in pl or "unit" in pl or "test" in (
            str(getattr(subtask, "content_role", None) or "")
        ).lower()
        if is_test_step:
            code_workers = {
                wid
                for wid, tgs in worker_tags.items()
                if "code" in (tgs or [])
            }
            if len(code_workers) >= 2:
                # Soft-avoid workers that only advertise free/chat without code
                weak = {
                    wid
                    for wid, tgs in worker_tags.items()
                    if "code" not in (tgs or [])
                }
                ban |= weak
        if ban:
            tags_map = {w: t for w, t in tags_map.items() if w not in ban}
            if not tags_map:
                tags_map = dict(worker_tags)  # no alternative — keep original
        if use_v2 or use_k:
            picks, reason = assign_k(
                subtask.tags,
                tags_map,
                k=k,
                health=health,
                stats=stats,
                usage=usage,
                assign_v2=use_v2,
                plan_size=plan_size,
            )
            subtask.assigned_workers = list(picks)
            subtask.assigned_worker = picks[0] if picks else None
            subtask.assignment_reason = reason
        else:
            worker = match_subtask_to_worker(subtask, tags_map, usage=usage)
            subtask.assigned_worker = worker
            subtask.assigned_workers = [worker] if worker else []
            subtask.assignment_reason = "legacy_least_used" if worker else None
            if worker:
                usage[worker] = usage.get(worker, 0) + 1

    _prefer_distinct_verify_workers(plan, worker_tags)
    return plan


def reassign_subtask_workers(
    plan: ConductorPlan,
    subtask_id: str,
    worker_tags: dict[str, list[str]],
    *,
    exclude_ids: set[str] | None = None,
    health: dict[str, bool] | None = None,
    k: int = 1,
) -> list[str]:
    """Re-pick workers for one subtask excluding failed ids. Returns new picks."""
    from routism_orch.assign import assign_k, get_worker_stats

    st = plan.get_subtask(subtask_id)
    if not st:
        return []
    ban = set(exclude_ids or ())
    tags_map = {w: t for w, t in worker_tags.items() if w not in ban}
    if not tags_map:
        tags_map = dict(worker_tags)
    usage = {wid: 0 for wid in tags_map}
    for other in plan.subtasks:
        if other.id == subtask_id:
            continue
        for w in other.assigned_workers or ([other.assigned_worker] if other.assigned_worker else []):
            if w in usage:
                usage[w] = usage.get(w, 0) + 1
    picks, reason = assign_k(
        st.tags,
        tags_map,
        k=max(1, k),
        health=health,
        stats=get_worker_stats(),
        usage=usage,
        assign_v2=True,
        plan_size=max(1, len(plan.subtasks)),
    )
    st.assigned_workers = list(picks)
    st.assigned_worker = picks[0] if picks else None
    st.assignment_reason = f"reassign:{reason}"
    st.error = None
    st.result = None
    st.samples = []
    st.selected_worker_id = None
    return list(picks)


def _guess_tags_for_text(text: str, available: set[str]) -> list[str]:
    """Soft map free text → pool tags. No domain templates; empty → first available."""
    t = (text or "").lower()
    guessed: list[str] = []
    # Only match against tags that actually exist on the pool.
    # Lightweight lexical hints — never invents a pipeline.
    hints: list[tuple[tuple[str, ...], str]] = [
        (("poem", "story", "creative", "brainstorm", "lyrics"), "creative"),
        (("explain", "teach", "eli5", "beginner", "summar"), "explain"),
        (("code", "function", "program", "debug", "script", "python", "typescript"), "code"),
        (("math", "prove", "equation", "calculate", "integral"), "math"),
        (("reason", "compare", "analy", "deduc", "tradeoff"), "reasoning"),
        (("summar", "tldr", "key point"), "summarize"),
        (("chat", "conversation", "reply"), "chat"),
    ]
    for keys, tag in hints:
        if tag in available and any(k in t for k in keys):
            guessed.append(tag)
    if not guessed:
        # Prefer neutral tags if present
        for pref in ("reasoning", "chat", "explain", "code"):
            if pref in available:
                return [pref]
        return [sorted(available)[0]] if available else ["general"]
    # Dedupe preserve order
    out: list[str] = []
    for g in guessed:
        if g not in out:
            out.append(g)
    return out


def extract_deliverables(query: str) -> list[dict[str, str]]:
    """Last-resort multi-part split when the LLM planner returns nothing.

    Domain-agnostic: does NOT invent design→implement→test pipelines or any
    demo shape. Only splits when the user language clearly sequences or
    separates work:

      1. Explicit sequence markers (then / after that / finally / …) → serial
      2. Clear multi-clause coordination with independent-looking parts

    Everything else returns [] so the caller falls back to parallel/single.
    Returns {role, intent, chain}.
    """
    q = (query or "").strip()
    if not q or len(q) < 12:
        return []

    # --- 1) Explicit sequence discourse only ---------------------------------
    parts = re.split(
        r"\b(?:and then|then|after that|afterward|afterwards|followed by|next|finally)\b",
        q,
        flags=re.IGNORECASE,
    )
    parts = [p.strip(" \t\n\r,.;:") for p in parts if p and p.strip(" \t\n\r,.;:")]
    # Reject empty crumbs only; short steps like "Do A" are valid sequence parts
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) >= 2:
        return [
            {
                "role": classify_subtask_role(p),
                "intent": p,
                "chain": "1",
            }
            for p in parts[:_MAX_PLAN_SUBTASKS]
        ]

    # --- 2) Explicit independence markers ------------------------------------
    # "X. Separately, Y" / "X; also Y" / "X. Independently, Y"
    indep = re.split(
        r"\b(?:separately|independently|in parallel|on the other hand)\b|,?\s+also\s+",
        q,
        flags=re.I,
    )
    indep = [p.strip(" \t\n\r,.;:") for p in indep if p and len(p.strip(" \t\n\r,.;:")) >= 12]
    if len(indep) >= 2:
        return [
            {
                "role": classify_subtask_role(p),
                "intent": p,
                "chain": "0",
            }
            for p in indep[:_MAX_PLAN_SUBTASKS]
        ]

    # No keyword-pipeline. Do not guess software steps from "design/implement/test".
    return []


def single_task_plan(
    query: str,
    worker_tags: dict[str, list[str]],
    *,
    health: dict[str, bool] | None = None,
) -> ConductorPlan:
    """One-node Conductor plan for the whole query (no parallel-vote fallback).

    Used when the LLM/heuristic produce no multi-step DAG so the product still
    stays on the Conductor path (assign + execute + synthesize).
    """
    available: set[str] = set()
    for tags in worker_tags.values():
        available.update(tags)
    tags = _guess_tags_for_text(query, available)
    st = Subtask(
        id="s1",
        prompt=(query or "").strip(),
        tags=tags,
        depends_on=[],
        success_criteria="Complete, useful answer to the user goal",
    )
    return finalize_plan(query, [st], worker_tags=worker_tags, health=health)


def heuristic_plan(
    query: str,
    worker_tags: dict[str, list[str]],
    *,
    health: dict[str, bool] | None = None,
) -> ConductorPlan:
    """Last-resort plan when the LLM planner returns an empty DAG.

    Only runs for explicitly multi-part user language (see extract_deliverables).
    Does not hardcode any demo domain or software pipeline. Each node intent is
    expanded into a full work order by enrich_subtask_prompts.
    """
    deliverables = extract_deliverables(query)
    if len(deliverables) < 2:
        return ConductorPlan(query=query, subtasks=[], layers=[])

    available: set[str] = set()
    for tags in worker_tags.values():
        available.update(tags)

    force_serial = any(str(d.get("chain") or "") in ("1", "true", "yes") for d in deliverables)

    subtasks: list[Subtask] = []
    for i, d in enumerate(deliverables[:_MAX_PLAN_SUBTASKS]):
        sid = f"s{i + 1}"
        intent = (d.get("intent") or "").strip()
        role = d.get("role") or classify_subtask_role(intent)
        tags = _guess_tags_for_text(intent, available)
        deps = [f"s{i}"] if force_serial and i > 0 else []
        subtasks.append(
            Subtask(
                id=sid,
                prompt=intent if intent.endswith((".", "?", "!")) else f"{intent}.",
                tags=tags,
                depends_on=deps,
                success_criteria=_default_success_criteria(role, intent),
            )
        )

    if force_serial:
        subtasks = merge_fragment_subtasks(subtasks)
        subtasks = cap_subtasks(subtasks, _MAX_PLAN_SUBTASKS)
        for i, st in enumerate(subtasks):
            st.depends_on = [] if i == 0 else [subtasks[i - 1].id]
    else:
        # Independent parts: keep parallel; still merge micro-fragments
        subtasks = merge_fragment_subtasks(subtasks)
        subtasks = cap_subtasks(subtasks, _MAX_PLAN_SUBTASKS)
        # Do NOT run software-shaped structural_repair pipelines on heuristic path
        for st in subtasks:
            if not force_serial:
                # keep existing deps (empty for indep)
                pass
    return finalize_plan(query, subtasks, worker_tags=worker_tags, health=health)