"""Phase 2C — curated eval task dataset.

A small, hand-picked set spanning reasoning + coding + summarization. Each task
carries `expect_contains` substrings (checked case-insensitively by the P2.D
reporter) — a cheap correctness smoke signal, NOT a gold test suite.

Keep expectations LOOSE (substring, not exact) so a correct-but-phrased
differently answer still passes the smoke check.
"""

from .eval import Task

TASKS: list[Task] = [
    Task(
        id="trivial-math",
        query="What is 7 * 6?",
        expect_contains=["42"],
    ),
    Task(
        id="reasoning-distance",
        query="A train goes 60km/h for 2 hours then 90km/h for 1 hour. What is the total distance?",
        expect_contains=["210"],
    ),
    Task(
        id="coding-fib",
        query="Write a Python function fib(n) that returns the nth Fibonacci number using iteration.",
        expect_contains=["def ", "return"],
    ),
    Task(
        id="summarize",
        query="Summarize this in one sentence: The Routism project builds a multi-LLM orchestrator. "
        "It decomposes complex queries into worker steps and routes them across a user-pluggable pool.",
        expect_contains=["routism", "orchestrator"],
    ),
]
