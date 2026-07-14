#!/usr/bin/env python3
"""OpenAI Chat Completions compatibility gate for coding agents.

Drives the real FastAPI ``POST /v1/chat/completions`` entry with Conductor
stubbed — proves stream framing, multi-turn fold, ignore-extras, and errors.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ROUTISM_ALLOW_ANON_LOOPBACK", "1")
os.environ.setdefault("ROUTISM_REQUIRE_API_KEY", "0")

passed = 0
failed = 0
LOG: list[str] = []


def log(msg: str) -> None:
    print(msg)
    LOG.append(msg)


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        log(f"  PASS  {name}")
    else:
        failed += 1
        log(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


FIXED_ANSWER = "HELLO_FROM_STUB_CONDUCTOR_42"


def test_prompt_fold() -> None:
    log("\n=== Prompt fold (shipped openai_compat.build_agent_prompt) ===")
    from routism.openai_compat import build_agent_prompt, normalize_content

    msgs = [
        {"role": "system", "content": "You are a coding assistant."},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "implement foo"},
    ]
    prompt = build_agent_prompt(msgs)
    check("includes system", "You are a coding assistant" in prompt, prompt[:200])
    check("includes history user", "first question" in prompt, prompt[:300])
    check("includes history assistant", "first answer" in prompt, prompt[:300])
    check("includes current request", "implement foo" in prompt and "Current request" in prompt)
    check("not last-user-only", "first question" in prompt and "implement foo" in prompt)

    try:
        build_agent_prompt([{"role": "assistant", "content": "nope"}])
        check("last non-user errors", False)
    except ValueError as e:
        check("last non-user errors", "user" in str(e).lower(), str(e))

    multi = normalize_content(
        [{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {"url": "x"}}]
    )
    check("multimodal text extract", "hello" in multi)


def test_sse_helpers() -> None:
    log("\n=== SSE helpers (shipped) ===")
    from routism.openai_compat import iter_sse_after_answer, chunk_text

    parts = list(iter_sse_after_answer(FIXED_ANSWER, model="routism-ultra", chunk_size=10))
    check("has frames", len(parts) >= 3)
    check("all data prefixed", all(p.startswith("data: ") for p in parts))
    check("ends with DONE", parts[-1].strip() == "data: [DONE]")
    joined = ""
    for p in parts:
        payload = p[len("data: ") :].strip()
        if payload == "[DONE]":
            continue
        obj = json.loads(payload)
        check("chunk object", obj.get("object") == "chat.completion.chunk", str(obj)[:80])
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if "content" in delta:
            joined += delta["content"]
    check("concat deltas == answer", joined == FIXED_ANSWER, repr(joined))
    check("chunk_text splits", "".join(chunk_text("abcdef", size=2)) == "abcdef")


def test_chat_route() -> None:
    log("\n=== Real /v1/chat/completions (stubbed conductor) ===")
    from starlette.testclient import TestClient
    import routism.server as srv

    def stub_conductor(query: str, user_id: str | None = None) -> dict:
        # Prove multi-turn fold reached conductor: echo marker if history present
        # user_id: multi-tenant vault pool path (optional; unused by stub answer)
        _ = user_id
        extra = ""
        if "System" in query or "History" in query:
            extra = " FOLDED_OK"
        return {
            "answer": FIXED_ANSWER + extra,
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
            "parallel": {},
            "budget_hit": False,
        }

    orig = srv._run_conductor_for_chat
    srv._run_conductor_for_chat = stub_conductor  # type: ignore[assignment]
    try:
        client = TestClient(srv.app)

        # models list
        r = client.get("/v1/models")
        check("GET models 200", r.status_code == 200, r.text)
        ids = [m.get("id") for m in (r.json().get("data") or [])]
        check("routism-ultra listed", "routism-ultra" in ids, str(ids))

        # ignore extras (tools)
        body = {
            "model": "routism-ultra",
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "hi1"},
                {"role": "assistant", "content": "yo"},
                {"role": "user", "content": "hi2"},
            ],
            "stream": False,
            "tools": [{"type": "function", "function": {"name": "search"}}],
            "tool_choice": "auto",
            "user": "agent-1",
        }
        r = client.post("/v1/chat/completions", json=body)
        check("non-stream with tools not 422", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
        data = r.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        check("non-stream content has stub", FIXED_ANSWER in content, content[:120])
        check("multi-turn folded into stub", "FOLDED_OK" in content, content[:120])
        check("usage present", "usage" in data and data["usage"].get("total_tokens") == 8)

        # n=2 → 400 openai error
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "routism-ultra",
                "n": 2,
                "messages": [{"role": "user", "content": "x"}],
            },
        )
        check("n=2 is 400", r.status_code == 400, r.text[:200])
        err = r.json()
        check("n=2 error.message", isinstance(err.get("error"), dict) and bool(err["error"].get("message")))

        # last role assistant → 400
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "routism-ultra",
                "messages": [{"role": "assistant", "content": "only ass"}],
            },
        )
        check("last non-user 400", r.status_code == 400, r.text[:200])
        check(
            "last non-user error shape",
            "error" in r.json() and "message" in r.json().get("error", {}),
        )

        # stream
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "routism-ultra",
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "stream please"}],
            },
        )
        check("stream status 200", r.status_code == 200, r.text[:200])
        ctype = r.headers.get("content-type", "")
        check("stream content-type event-stream", "text/event-stream" in ctype, ctype)
        raw = r.text
        check("stream has data lines", "data: " in raw)
        check("stream ends DONE", "data: [DONE]" in raw)
        joined = ""
        objects = []
        for line in raw.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: ") :].strip()
            if payload == "[DONE]":
                continue
            obj = json.loads(payload)
            objects.append(obj)
            check(
                "stream chunk type",
                obj.get("object") == "chat.completion.chunk",
                str(obj.get("object")),
            )
            ch0 = (obj.get("choices") or [{}])[0]
            delta = ch0.get("delta") or {}
            if delta.get("content"):
                joined += delta["content"]
        check("stream concat has fixed answer", FIXED_ANSWER in joined, joined[:80])
        check("stream has role or content chunks", len(objects) >= 2)

        # stream_options include_usage → some chunk has usage
        has_usage = any("usage" in o for o in objects)
        check("include_usage chunk", has_usage)

        # --- 401 when ROUTISM_REQUIRE_API_KEY=1 and no/invalid key ---
        prev_req = os.environ.get("ROUTISM_REQUIRE_API_KEY")
        os.environ["ROUTISM_REQUIRE_API_KEY"] = "1"
        try:
            r401 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "routism-ultra",
                    "messages": [{"role": "user", "content": "auth please"}],
                },
            )
            check("require key 401 status", r401.status_code == 401, r401.text[:200])
            body401 = r401.json()
            err401 = body401.get("error") or {}
            check(
                "401 has error.message",
                isinstance(err401, dict) and bool(err401.get("message")),
                str(body401)[:200],
            )
            check(
                "401 has error.type",
                isinstance(err401, dict) and bool(err401.get("type")),
                str(body401)[:200],
            )
            check(
                "401 not FastAPI detail-only",
                "detail" not in body401 or "error" in body401,
                str(body401)[:200],
            )
            check(
                "401 code invalid_api_key",
                err401.get("code") == "invalid_api_key",
                str(err401),
            )
        finally:
            if prev_req is None:
                os.environ.pop("ROUTISM_REQUIRE_API_KEY", None)
            else:
                os.environ["ROUTISM_REQUIRE_API_KEY"] = prev_req

    finally:
        srv._run_conductor_for_chat = orig  # type: ignore[assignment]


def main() -> int:
    log("=== OpenAI agent compatibility gate ===\n")
    test_prompt_fold()
    test_sse_helpers()
    test_chat_route()
    log(f"\n=== Summary: {passed} passed, {failed} failed ===")

    # Optional evidence dir: env or portable temp — never a machine-specific absolute path.
    import tempfile

    scratch = os.environ.get("ROUTISM_GATE_SCRATCH") or str(
        Path(tempfile.gettempdir()) / "routism_openai_compat_gate"
    )
    Path(scratch).mkdir(parents=True, exist_ok=True)
    full = "\n".join(LOG) + "\n"
    (Path(scratch) / "openai_compat_gate.log").write_text(full, encoding="utf-8")
    (Path(scratch) / "openai_compat_live_note.txt").write_text(
        "Live openai SDK + real Conductor pool smoke not required; "
        "gate uses stubbed _run_conductor_for_chat on real FastAPI route.\n",
        encoding="utf-8",
    )
    log(f"Wrote evidence under {scratch}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
