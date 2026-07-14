"""Phase 2A — Eval harness scaffold.

System-agnostic benchmark runner. A "System" is anything exposing
`run(query) -> RunResult`. The Benchmark loops a task set, times each call, and
records the result without ever crashing the whole suite. Tokens are whatever
the system reports (real systems measure; stubs return 0).

Kept stdlib-only on purpose — no new dependencies.
"""

from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RunResult:
    answer: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Task:
    id: str
    query: str
    expect_contains: list[str] | None = None


@dataclass
class Record:
    task_id: str
    query: str
    system_name: str
    answer: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    ok: bool
    error: str | None = None


@runtime_checkable
class System(Protocol):
    def run(self, query: str) -> RunResult:  # pragma: no cover - protocol
        ...


class Benchmark:
    def __init__(self, tasks: list[Task]):
        self.tasks = list(tasks)

    def run_system(self, system: System, name: str) -> list[Record]:
        """Run every task through `system`, returning one Record per task.

        Exceptions from a single task are captured into `ok=False` + `error` so
        one bad task never aborts the whole suite.
        """
        records: list[Record] = []
        for task in self.tasks:
            start = time.perf_counter()
            try:
                res = system.run(task.query)
                ok = True
                err: str | None = None
            except Exception as e:  # noqa: BLE001 - harness must be resilient
                res = RunResult(answer="", input_tokens=0, output_tokens=0)
                ok = False
                err = f"{type(e).__name__}: {e}"
            latency_ms = (time.perf_counter() - start) * 1000.0
            records.append(
                Record(
                    task_id=task.id,
                    query=task.query,
                    system_name=name,
                    answer=res.answer,
                    input_tokens=res.input_tokens,
                    output_tokens=res.output_tokens,
                    latency_ms=round(latency_ms, 2),
                    ok=ok,
                    error=err,
                )
            )
        return records


# Tiny built-in smoke set so the gate runs without a dataset file.
SMOKE_TASKS: list[Task] = [
    Task(id="t1", query="What is 2 + 2?", expect_contains=None),
    Task(id="t2", query="Explain what TCP handshake means in one sentence.", expect_contains=None),
]


@dataclass
class SystemStats:
    """Aggregated metrics for one System over a task set."""

    name: str
    n: int
    ok_count: int
    correct_count: int
    accuracy: float
    total_in_tokens: int
    total_out_tokens: int
    total_tokens: int
    total_latency_ms: float
    avg_latency_ms: float


@dataclass
class Report:
    """RouterBench-style comparison across systems.

    - accuracy via `expect_contains` (loose substring, case-insensitive)
    - token + latency totals per system
    - token overhead ratio vs a chosen baseline (default "zerorouter")
    - per-task win/loss classification (both / routism-only / baseline-only /
      neither) so we can see WHERE orchestration helps or hurts.
    """

    systems: dict[str, SystemStats]
    baseline: str | None
    overhead_ratio: float | None
    win_loss: dict[str, int]

    def __str__(self) -> str:
        lines = ["# RouterBench-style report", ""]
        header = f"{'system':<14}{'n':>4}{'ok':>5}{'acc%':>8}{'in_tok':>9}{'out_tok':>9}{'tot_tok':>9}{'avg_ms':>9}"
        lines.append(header)
        lines.append("-" * len(header))
        for name, s in self.systems.items():
            lines.append(
                f"{name:<14}{s.n:>4}{s.ok_count:>5}{s.accuracy*100:>7.1f}{s.total_in_tokens:>9}"
                f"{s.total_out_tokens:>9}{s.total_tokens:>9}{s.avg_latency_ms:>9.2f}"
            )
        if self.overhead_ratio is not None:
            base = self.baseline or "?"
            lines.append("")
            lines.append(f"token overhead ratio vs '{base}': {self.overhead_ratio:.2f}x")
        lines.append("")
        lines.append("win/loss (per task):")
        for k, v in self.win_loss.items():
            lines.append(f"  {k:<22}{v}")
        return "\n".join(lines)


class Reporter:
    """Aggregates Benchmark Records into a RouterBench-style Report."""

    @staticmethod
    def _is_correct(rec: Record, expects: list[str] | None) -> bool:
        if not rec.ok:
            return False
        if not expects:
            return True
        low = rec.answer.lower()
        return all(sub.lower() in low for sub in expects)

    @classmethod
    def build(
        cls,
        tasks: list[Task],
        records: dict[str, list[Record]],
        baseline: str = "zerorouter",
    ) -> Report:
        by_task: dict[str, dict[str, bool]] = {t.id: {} for t in tasks}
        expect = {t.id: t.expect_contains for t in tasks}
        stats: dict[str, SystemStats] = {}

        for name, recs in records.items():
            assert len(recs) == len(tasks), f"{name}: record count != task count"
            ok = sum(1 for r in recs if r.ok)
            correct = sum(1 for r in recs if cls._is_correct(r, expect[r.task_id]))
            tin = sum(r.input_tokens for r in recs)
            tout = sum(r.output_tokens for r in recs)
            lat = sum(r.latency_ms for r in recs)
            stats[name] = SystemStats(
                name=name,
                n=len(recs),
                ok_count=ok,
                correct_count=correct,
                accuracy=(correct / len(recs)) if recs else 0.0,
                total_in_tokens=tin,
                total_out_tokens=tout,
                total_tokens=tin + tout,
                total_latency_ms=round(lat, 2),
                avg_latency_ms=round(lat / len(recs), 2) if recs else 0.0,
            )
            for r in recs:
                by_task[r.task_id][name] = cls._is_correct(r, expect[r.task_id])

        # Overhead ratio: this suite's total tokens / baseline total tokens.
        overhead: float | None = None
        if baseline in stats:
            base_tok = stats[baseline].total_tokens
            if base_tok:
                primary = next((n for n in stats if n != baseline), None)
                if primary is not None:
                    overhead = round(stats[primary].total_tokens / base_tok, 2)

        # Per-task win/loss vs baseline.
        wl = {"both_correct": 0, "routism_only": 0, "baseline_only": 0, "neither": 0}
        for tid, d in by_task.items():
            if baseline not in d:
                continue
            base_ok = d[baseline]
            others = [v for k, v in d.items() if k != baseline]
            any_other = any(others) if others else False
            if base_ok and any_other:
                wl["both_correct"] += 1
            elif base_ok and not any_other:
                wl["baseline_only"] += 1
            elif not base_ok and any_other:
                wl["routism_only"] += 1
            else:
                wl["neither"] += 1

        return Report(
            systems=stats,
            baseline=baseline if baseline in stats else None,
            overhead_ratio=overhead,
            win_loss=wl,
        )


def run_and_persist(
    tasks: list[Task],
    systems: dict[str, System],
    path: str,
    baseline: str = "zerorouter",
) -> Report:
    """Run every system over `tasks`, build a Report, and write it (as a
    machine-readable JSON + a human summary) to `path`. Returns the Report.

    Used by the P2.E final gate so Phase-2 results are durable and the #3
    verdict can be re-examined later against real (live) numbers.
    """
    records: dict[str, list[Record]] = {}
    for name, system in systems.items():
        records[name] = Benchmark(tasks).run_system(system, name)
    report = Reporter.build(tasks, records, baseline=baseline)

    payload = {
        "baseline": report.baseline,
        "overhead_ratio": report.overhead_ratio,
        "win_loss": report.win_loss,
        "systems": {
            name: {
                "n": s.n,
                "ok_count": s.ok_count,
                "correct_count": s.correct_count,
                "accuracy": s.accuracy,
                "total_in_tokens": s.total_in_tokens,
                "total_out_tokens": s.total_out_tokens,
                "total_tokens": s.total_tokens,
                "avg_latency_ms": s.avg_latency_ms,
            }
            for name, s in report.systems.items()
        },
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    # Append the human-readable summary so the file is self-explanatory.
    with open(path, "a") as f:
        f.write("\n\n# summary\n\n")
        f.write(str(report))
        f.write("\n")
    return report
