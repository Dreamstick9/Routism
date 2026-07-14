"""Installation-scoped API keys (no user accounts / login).

Keys are for agents and optional dashboard auth. Secrets shown once at create;
only SHA-256 hashes stored. Bootstrap via ROUTISM_API_KEY or first-boot file.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

_API_KEY_PREFIX = "rtm_"
INSTALL_ID = "install"  # single-tenant placeholder (no multi-user)


def _data_dir() -> Path:
    raw = os.environ.get("ROUTISM_DATA_DIR", "").strip()
    if raw:
        p = Path(raw)
    else:
        p = Path(__file__).resolve().parent.parent / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _new_api_key() -> str:
    return _API_KEY_PREFIX + secrets.token_urlsafe(32)


def require_api_key_enforced() -> bool:
    return os.environ.get("ROUTISM_REQUIRE_API_KEY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def open_local_mutations() -> bool:
    """When true, key create/list on loopback without prior key (default on)."""
    raw = os.environ.get("ROUTISM_OPEN_LOCAL", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def allow_anon_loopback() -> bool:
    raw = os.environ.get("ROUTISM_ALLOW_ANON_LOOPBACK", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


@dataclass
class ApiKeyMeta:
    id: str
    name: str
    key_prefix: str
    created_at: float
    last_used_at: float | None
    revoked_at: float | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "revoked": self.revoked_at is not None,
        }


class ApiKeyStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        key_hash TEXT NOT NULL UNIQUE,
                        key_prefix TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        last_used_at REAL,
                        revoked_at REAL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)"
                )
                conn.commit()
            finally:
                conn.close()

    def _row(self, r: sqlite3.Row) -> ApiKeyMeta:
        return ApiKeyMeta(
            id=r["id"],
            name=r["name"],
            key_prefix=r["key_prefix"],
            created_at=float(r["created_at"]),
            last_used_at=float(r["last_used_at"]) if r["last_used_at"] is not None else None,
            revoked_at=float(r["revoked_at"]) if r["revoked_at"] is not None else None,
        )

    def create(self, name: str = "default") -> tuple[ApiKeyMeta, str]:
        nm = (name or "default").strip()[:64] or "default"
        kid = "key_" + uuid.uuid4().hex[:16]
        raw = _new_api_key()
        h = _hash_api_key(raw)
        prefix = raw[:10] + "…"
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO api_keys
                    (id, user_id, name, key_hash, key_prefix, created_at, last_used_at, revoked_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (kid, INSTALL_ID, nm, h, prefix, now),
                )
                conn.commit()
            finally:
                conn.close()
        return ApiKeyMeta(kid, nm, prefix, now, None, None), raw

    def import_raw(self, raw: str, name: str = "bootstrap") -> ApiKeyMeta:
        """Register an existing raw key (e.g. from ROUTISM_API_KEY)."""
        raw = (raw or "").strip()
        if not raw.startswith(_API_KEY_PREFIX):
            raise ValueError("API key must start with rtm_")
        h = _hash_api_key(raw)
        with self._lock:
            conn = self._connect()
            try:
                existing = conn.execute(
                    "SELECT * FROM api_keys WHERE key_hash = ?", (h,)
                ).fetchone()
                if existing:
                    return self._row(existing)
                kid = "key_" + uuid.uuid4().hex[:16]
                prefix = raw[:10] + "…"
                now = time.time()
                nm = (name or "bootstrap").strip()[:64]
                conn.execute(
                    """
                    INSERT INTO api_keys
                    (id, user_id, name, key_hash, key_prefix, created_at, last_used_at, revoked_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (kid, INSTALL_ID, nm, h, prefix, now),
                )
                conn.commit()
                return ApiKeyMeta(kid, nm, prefix, now, None, None)
            finally:
                conn.close()

    def list_active(self) -> list[ApiKeyMeta]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM api_keys
                    WHERE revoked_at IS NULL
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            finally:
                conn.close()
        return [self._row(r) for r in rows]

    def count_active(self) -> int:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM api_keys WHERE revoked_at IS NULL"
                ).fetchone()
                return int(row["c"] if row else 0)
            finally:
                conn.close()

    def revoke(self, key_id: str) -> bool:
        kid = (key_id or "").strip()
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    UPDATE api_keys SET revoked_at = ?
                    WHERE id = ? AND revoked_at IS NULL
                    """,
                    (now, kid),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def is_valid(self, raw_key: str) -> bool:
        return self.resolve(raw_key) is not None

    def resolve(self, raw_key: str) -> str | None:
        """Return key id if valid non-revoked; touch last_used."""
        if not raw_key or not raw_key.strip():
            return None
        h = _hash_api_key(raw_key.strip())
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT * FROM api_keys
                    WHERE key_hash = ? AND revoked_at IS NULL
                    """,
                    (h,),
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
                conn.commit()
                return row["id"]
            finally:
                conn.close()


_STORE: ApiKeyStore | None = None
_LOCK = threading.Lock()
_BOOTSTRAPPED = False


def get_api_key_store() -> ApiKeyStore:
    global _STORE
    with _LOCK:
        if _STORE is None:
            path = os.environ.get(
                "ROUTISM_API_KEYS_PATH",
                str(_data_dir() / "api_keys.db"),
            )
            _STORE = ApiKeyStore(path)
        return _STORE


def reset_api_key_store_for_tests() -> None:
    global _STORE, _BOOTSTRAPPED
    with _LOCK:
        _STORE = None
        _BOOTSTRAPPED = False


def ensure_bootstrap_key() -> str | None:
    """Import ROUTISM_API_KEY or mint first key; write bootstrap_key.txt once.

    Returns the raw bootstrap key if one was minted this process, else None.
    """
    global _BOOTSTRAPPED
    store = get_api_key_store()
    env_key = os.environ.get("ROUTISM_API_KEY", "").strip()
    if env_key:
        try:
            store.import_raw(env_key, name="env-bootstrap")
        except ValueError as e:
            _log.warning("ROUTISM_API_KEY invalid: %s", e)
        _BOOTSTRAPPED = True
        return None

    if store.count_active() > 0:
        _BOOTSTRAPPED = True
        return None

    meta, raw = store.create(name="bootstrap")
    path = _data_dir() / "bootstrap_key.txt"
    try:
        path.write_text(
            raw + "\n# First-boot API key — treat as secret. Create more via /v1/keys\n",
            encoding="utf-8",
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError as e:
        _log.warning("could not write bootstrap_key.txt: %s", e)
    _log.warning(
        "Routism minted bootstrap API key (also in %s). Use as Authorization: Bearer …",
        path,
    )
    _BOOTSTRAPPED = True
    return raw


def extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
        return tok or None
    return None


def is_loopback_host(host: str | None) -> bool:
    h = (host or "").split("%")[0].lower()
    return h in ("127.0.0.1", "::1", "localhost", "testclient")


def authorize_request(
    authorization: str | None,
    *,
    client_host: str | None = None,
    for_mutation: bool = False,
) -> bool:
    """Return True if request is allowed.

    - Valid API key always OK.
    - If ROUTISM_REQUIRE_API_KEY=1: Bearer key required (use when exposed to the internet).
    - Else open install mode (default Docker desktop):
        OPEN_LOCAL / ALLOW_ANON_LOOPBACK gate access without a key.
        Host→container traffic is *not* loopback, so we must not require 127.0.0.1
        for the default open self-hosted experience.
    """
    tok = extract_bearer(authorization)
    if tok and get_api_key_store().is_valid(tok):
        return True
    if require_api_key_enforced():
        return False
    # Default self-hosted / Docker: open when flags allow (not loopback-only).
    if for_mutation:
        return open_local_mutations()
    return allow_anon_loopback()


def require_auth(
    authorization: str | None,
    request: Request | None = None,
    *,
    for_mutation: bool = False,
) -> None:
    host = None
    if request is not None and request.client:
        host = request.client.host
    if not authorize_request(authorization, client_host=host, for_mutation=for_mutation):
        raise HTTPException(
            status_code=401,
            detail="authentication required (Bearer API key)",
        )


# ---------------------------------------------------------------------------
# HTTP routes: /v1/keys
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/keys", tags=["keys"])


class CreateKeyBody(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=64)


@router.get("")
def list_keys(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    require_auth(authorization, request, for_mutation=False)
    keys = get_api_key_store().list_active()
    base = os.environ.get("ROUTISM_PUBLIC_BASE_URL", "http://localhost:8000/v1")
    return {
        "keys": [k.public_dict() for k in keys],
        "base_url": base,
        "model": "routism-ultra",
    }


@router.post("")
def create_key(
    body: CreateKeyBody,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    require_auth(authorization, request, for_mutation=True)
    meta, raw = get_api_key_store().create(name=body.name)
    return {
        "key": meta.public_dict(),
        "secret": raw,
        "message": "Copy this secret now; it will not be shown again.",
    }


@router.delete("/{key_id}")
def revoke_key(
    key_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    require_auth(authorization, request, for_mutation=True)
    ok = get_api_key_store().revoke(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found or already revoked")
    return {"ok": True, "revoked": key_id}
