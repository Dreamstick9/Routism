"""Simple in-process rate limiting for public API surfaces."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _limit() -> int:
    try:
        return max(1, int(os.environ.get("ROUTISM_RATE_LIMIT_PER_MIN", "120")))
    except ValueError:
        return 120


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket-ish sliding window: N requests / 60s per client IP."""

    def __init__(self, app, *, per_minute: int | None = None):
        super().__init__(app)
        self.per_minute = per_minute or _limit()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _client_key(self, request: Request) -> str:
        # Prefer first X-Forwarded-For hop when behind a trusted proxy
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()[:64]
        if request.client:
            return (request.client.host or "unknown")[:64]
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip health for probes
        path = request.url.path or ""
        if path in ("/v1/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        key = self._client_key(request)
        now = time.time()
        window = 60.0
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= self.per_minute:
                return JSONResponse(
                    {
                        "error": "rate_limit_exceeded",
                        "detail": f"max {self.per_minute} requests per minute",
                    },
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            q.append(now)
        return await call_next(request)
