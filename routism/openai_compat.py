"""OpenAI Chat Completions compatibility helpers for coding agents / harnesses.

Pure formatting + prompt folding — no Conductor I/O. Used by
``POST /v1/chat/completions`` so external agents can use Routism as
``base_url`` + model ``routism-ultra``.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Iterator


# Caps for agent multi-turn context (characters).
_HISTORY_CAP = 24_000
_CURRENT_CAP = 8_000
_SYSTEM_CAP = 8_000


def completion_id() -> str:
    return f"chatcmpl-{secrets.token_hex(12)}"


def normalize_content(content: Any) -> str:
    """Normalize message content: string or multimodal list → plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" or "text" in item:
                    parts.append(str(item.get("text") or ""))
                # image_url and other parts ignored (agents may send them)
        return "\n".join(p for p in parts if p)
    return str(content)


def build_agent_prompt(
    messages: list[Any],
    *,
    history_cap: int = _HISTORY_CAP,
    current_cap: int = _CURRENT_CAP,
    system_cap: int = _SYSTEM_CAP,
) -> str:
    """Fold OpenAI-style messages into a single Conductor query string.

    Raises ValueError if empty or last message is not role=user.
    """
    if not messages:
        raise ValueError("messages must be a non-empty array")

    normalized: list[tuple[str, str]] = []
    for m in messages:
        if isinstance(m, dict):
            role = str(m.get("role") or "user").strip().lower()
            text = normalize_content(m.get("content"))
        else:
            role = str(getattr(m, "role", "user") or "user").strip().lower()
            text = normalize_content(getattr(m, "content", None))
        normalized.append((role, text))

    last_role, last_text = normalized[-1]
    if last_role != "user":
        raise ValueError("last message must have role 'user'")
    if not (last_text or "").strip():
        raise ValueError("messages must contain a non-empty user query")

    systems = [t for r, t in normalized[:-1] if r == "system" and (t or "").strip()]
    history = [(r, t) for r, t in normalized[:-1] if r in ("user", "assistant") and (t or "").strip()]

    system_block = ""
    if systems:
        joined = "\n\n".join(systems)
        if len(joined) > system_cap:
            joined = joined[:system_cap]
        system_block = f"## System\n{joined.strip()}\n\n"

    # Build history from newest-prior backwards until cap, then reverse
    hist_lines: list[str] = []
    used = 0
    for role, text in reversed(history):
        label = "User" if role == "user" else "Assistant"
        piece = f"{label}: {text.strip()}"
        if used + len(piece) + 1 > history_cap:
            # try truncated piece
            remain = history_cap - used - len(label) - 2
            if remain < 40:
                break
            piece = f"{label}: {text.strip()[:remain]}"
            hist_lines.append(piece)
            break
        hist_lines.append(piece)
        used += len(piece) + 1
    hist_lines.reverse()
    history_block = ""
    if hist_lines:
        history_block = "## History\n" + "\n".join(hist_lines) + "\n\n"

    current = last_text.strip()
    if len(current) > current_cap:
        current = current[:current_cap]

    return f"{system_block}{history_block}## Current request\n{current}".strip()


def format_error(
    message: str,
    *,
    type_: str = "invalid_request_error",
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    """OpenAI-shaped error body."""
    err: dict[str, Any] = {
        "message": message,
        "type": type_,
        "param": param,
        "code": code,
    }
    return {"error": err}


def format_completion(
    answer: str,
    *,
    model: str,
    usage: dict[str, Any] | None = None,
    completion_id_str: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Non-stream chat.completion object."""
    u = usage or {}
    body: dict[str, Any] = {
        "id": completion_id_str or completion_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer or ""},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(
                u.get("total_tokens")
                or (int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0))
            ),
        },
    }
    if extra:
        body.update(extra)
    return body


def _chunk_dict(
    *,
    cid: str,
    model: str,
    created: int,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def sse_data(obj: dict[str, Any] | str) -> str:
    if isinstance(obj, str):
        return f"data: {obj}\n\n"
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def chunk_text(text: str, *, size: int = 48) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]


def iter_sse_after_answer(
    answer: str,
    *,
    model: str,
    usage: dict[str, Any] | None = None,
    include_usage: bool = False,
    chunk_size: int = 48,
    completion_id_str: str | None = None,
) -> Iterator[str]:
    """Yield OpenAI SSE frames for a completed answer (post-hoc stream)."""
    cid = completion_id_str or completion_id()
    created = int(time.time())
    yield sse_data(_chunk_dict(cid=cid, model=model, created=created, delta={"role": "assistant"}))
    for piece in chunk_text(answer or "", size=chunk_size):
        if piece:
            yield sse_data(
                _chunk_dict(cid=cid, model=model, created=created, delta={"content": piece})
            )
    yield sse_data(
        _chunk_dict(cid=cid, model=model, created=created, delta={}, finish_reason="stop")
    )
    if include_usage:
        u = usage or {}
        usage_chunk = _chunk_dict(cid=cid, model=model, created=created, delta={})
        usage_chunk["usage"] = {
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(
                u.get("total_tokens")
                or (int(u.get("prompt_tokens") or 0) + int(u.get("completion_tokens") or 0))
            ),
        }
        yield sse_data(usage_chunk)
    yield sse_data("[DONE]")


def sse_role_chunk(model: str, *, completion_id_str: str | None = None) -> tuple[str, str, int]:
    """First stream frame: assistant role. Returns (sse_text, id, created)."""
    cid = completion_id_str or completion_id()
    created = int(time.time())
    frame = sse_data(_chunk_dict(cid=cid, model=model, created=created, delta={"role": "assistant"}))
    return frame, cid, created


def sse_keepalive_chunk(model: str, cid: str, created: int) -> str:
    """Empty delta keepalive (valid OpenAI-shaped chunk)."""
    return sse_data(_chunk_dict(cid=cid, model=model, created=created, delta={}))


def apply_max_tokens(answer: str, max_tokens: int | None) -> str:
    """Soft cap on final answer length (~4 chars/token heuristic)."""
    if max_tokens is None or max_tokens <= 0:
        return answer or ""
    cap = int(max_tokens) * 4
    text = answer or ""
    if len(text) <= cap:
        return text
    return text[:cap]
