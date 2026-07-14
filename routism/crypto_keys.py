"""BYOK / secret encryption helpers (Fernet).

Encrypts worker API keys (and similar short secrets) at rest in ``routism.yaml``.

Key material (first match wins):
1. ``ROUTISM_FERNET_KEY`` — a valid Fernet key (url-safe base64, 32 bytes).
2. ``ROUTISM_SECRETS_KEY`` — any passphrase; derived via PBKDF2-HMAC-SHA256
   (dev convenience; prefer a real Fernet key in production).

Ciphertext format: ``enc:v1:<fernet-token>`` so plaintext legacy values can
be detected and left untouched by ``decrypt_secret``.

Migration (existing plaintext ``api_key`` in YAML)
-------------------------------------------------
1. Set ``ROUTISM_FERNET_KEY`` (or ``ROUTISM_SECRETS_KEY`` for local dev).
2. New/updated workers via ``POST /v1/management/pool`` encrypt on write.
3. Call sites use ``decrypt_secret`` / ``resolve_api_key`` so both plaintext
   legacy keys and ``enc:v1:`` values work until re-saved.
4. Optional bulk migrate: load Settings, encrypt each plaintext api_key, save.
   Do **not** re-encrypt values that already start with ``enc:v1:``.

This is a practical baseline, not a compliance guarantee (key management,
rotation, and access control remain the operator's responsibility).
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading

# Prefix marks values produced by this module (versioned for future algos).
_PREFIX = "enc:v1:"

# Fixed salt for PBKDF2 derivation from ROUTISM_SECRETS_KEY. Not secret;
# uniqueness comes from the passphrase. Change only with a full re-encrypt.
_PBKDF2_SALT = b"routism-secrets-v1"
_PBKDF2_ROUNDS = 390_000

_lock = threading.Lock()
_cached_key_source: str | None = None
_cached_fernet: object | None = None


class CryptoKeysError(RuntimeError):
    """Missing/invalid key material or encrypt/decrypt failure."""


def _fernet_mod():
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as e:  # pragma: no cover
        raise CryptoKeysError(
            "cryptography package required for secret encryption "
            "(pip install cryptography)"
        ) from e
    return Fernet, InvalidToken


def _derive_fernet_key_from_passphrase(passphrase: str) -> bytes:
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        _PBKDF2_SALT,
        _PBKDF2_ROUNDS,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


def _local_key_path() -> str:
    """Stable on-disk key for local/dev when env is unset (gitignored under data/)."""
    override = os.environ.get("ROUTISM_LOCAL_FERNET_PATH", "").strip()
    if override:
        return override
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return str(root / "data" / "local_fernet.key")


def _ensure_local_fernet_key() -> str:
    """Load or create a Fernet key file so vault/BYOK works out of the box locally.

    Production should still set ROUTISM_FERNET_KEY / ROUTISM_SECRETS_KEY explicitly.
    Opt out with ROUTISM_DISABLE_LOCAL_FERNET=1 (then missing env fails closed).
    """
    if os.environ.get("ROUTISM_DISABLE_LOCAL_FERNET", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        raise CryptoKeysError(
            "No encryption key configured. Set ROUTISM_FERNET_KEY "
            "(preferred) or ROUTISM_SECRETS_KEY (dev PBKDF2 derivation)."
        )
    from pathlib import Path

    path = Path(_local_key_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    Fernet, _ = _fernet_mod()
    key = Fernet.generate_key().decode("ascii")
    path.write_text(key + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


def _load_fernet():
    """Resolve Fernet from env; cache until the key source env changes."""
    global _cached_key_source, _cached_fernet

    Fernet, _InvalidToken = _fernet_mod()
    fernet_key = os.environ.get("ROUTISM_FERNET_KEY", "").strip()
    secrets_key = os.environ.get("ROUTISM_SECRETS_KEY", "").strip()
    local_path = _local_key_path() if not fernet_key and not secrets_key else ""
    source = (
        f"fernet:{fernet_key}"
        if fernet_key
        else (f"secrets:{secrets_key}" if secrets_key else f"localfile:{local_path}")
    )

    with _lock:
        if _cached_fernet is not None and _cached_key_source == source:
            return _cached_fernet

        if fernet_key:
            try:
                f = Fernet(
                    fernet_key.encode("ascii")
                    if isinstance(fernet_key, str)
                    else fernet_key
                )
            except Exception as e:  # noqa: BLE001
                raise CryptoKeysError(
                    f"ROUTISM_FERNET_KEY is not a valid Fernet key: {type(e).__name__}: {e}"
                ) from e
        elif secrets_key:
            f = Fernet(_derive_fernet_key_from_passphrase(secrets_key))
        else:
            # Local/dev: auto key file so Providers/vault do not 503 on first use
            auto = _ensure_local_fernet_key()
            f = Fernet(auto.encode("ascii"))

        _cached_key_source = source
        _cached_fernet = f
        return f


def reset_key_cache() -> None:
    """Drop cached Fernet (for tests when env keys change)."""
    global _cached_key_source, _cached_fernet
    with _lock:
        _cached_key_source = None
        _cached_fernet = None


def has_key_material() -> bool:
    """True if env or auto local key file can encrypt secrets."""
    if os.environ.get("ROUTISM_FERNET_KEY", "").strip() or os.environ.get(
        "ROUTISM_SECRETS_KEY", ""
    ).strip():
        return True
    if os.environ.get("ROUTISM_DISABLE_LOCAL_FERNET", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    # Auto local key is always available unless disabled
    return True


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(_PREFIX)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string. Returns ``enc:v1:<token>``."""
    if plaintext is None:
        raise CryptoKeysError("cannot encrypt None")
    text = str(plaintext)
    if not text:
        raise CryptoKeysError("cannot encrypt empty secret")
    if is_encrypted(text):
        return text  # idempotent: already ciphertext
    token = _load_fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    """Decrypt ``enc:v1:`` values; pass through plaintext legacy secrets.

    Raises ``CryptoKeysError`` if the value looks encrypted but cannot be
    decrypted (wrong key / corrupt token).
    """
    if value is None:
        return value  # type: ignore[return-value]
    text = str(value)
    if not text:
        return text
    if not is_encrypted(text):
        return text  # legacy plaintext in YAML
    _Fernet, InvalidToken = _fernet_mod()
    token = text[len(_PREFIX) :].encode("ascii")
    try:
        return _load_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as e:
        raise CryptoKeysError(
            "failed to decrypt secret (wrong ROUTISM_FERNET_KEY / ROUTISM_SECRETS_KEY?)"
        ) from e
    except CryptoKeysError:
        raise
    except Exception as e:  # noqa: BLE001
        raise CryptoKeysError(f"decrypt failed: {type(e).__name__}: {e}") from e


def resolve_api_key(value: str | None) -> str | None:
    """Return a usable API key for HTTP Authorization headers.

    Decrypts ``enc:v1:`` blobs; returns plaintext legacy keys unchanged.
    ``None`` / empty stay as-is.
    """
    if value is None or value == "":
        return value
    return decrypt_secret(value)


def generate_fernet_key() -> str:
    """Generate a new Fernet key string (for ops docs / setup)."""
    Fernet, _ = _fernet_mod()
    return Fernet.generate_key().decode("ascii")
