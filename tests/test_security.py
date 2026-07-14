#!/usr/bin/env python3
"""Security baseline gate: SSRF URL validation + Fernet BYOK encrypt roundtrip."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    print("=== Security baseline gate (SSRF + BYOK crypto) ===\n")

    # Isolate env for deterministic tests
    for k in (
        "ROUTISM_ALLOW_PRIVATE_URLS",
        "ALLOW_LOCAL_HTTP",
        "ROUTISM_SSRF_RESOLVE",
        "ROUTISM_FERNET_KEY",
        "ROUTISM_SECRETS_KEY",
    ):
        os.environ.pop(k, None)

    from cryptography.fernet import Fernet

    from routism.crypto_keys import (
        CryptoKeysError,
        decrypt_secret,
        encrypt_secret,
        generate_fernet_key,
        has_key_material,
        is_encrypted,
        reset_key_cache,
        resolve_api_key,
    )
    from routism.security_ssrf import SSRFBlocked, validate_worker_base_url

    # ------------------------------------------------------------------ SSRF
    print("--- SSRF ---")
    # Defaults: private blocked, http blocked, resolve on.
    os.environ["ROUTISM_ALLOW_PRIVATE_URLS"] = "0"
    os.environ["ALLOW_LOCAL_HTTP"] = "0"
    os.environ["ROUTISM_SSRF_RESOLVE"] = "0"  # avoid DNS flakiness for unit cases

    def blocked(url: str, label: str) -> None:
        try:
            validate_worker_base_url(url)
            check(label, False, f"should block {url!r}")
        except SSRFBlocked as e:
            check(label, True, str(e))

    def allowed(url: str, label: str) -> None:
        try:
            out = validate_worker_base_url(url)
            check(label, out == url.strip(), f"got {out!r}")
        except SSRFBlocked as e:
            check(label, False, str(e))

    blocked("http://169.254.169.254/latest/meta-data/", "block metadata IP over http")
    blocked("https://169.254.169.254/latest/meta-data/", "block metadata IP over https")
    blocked("https://169.254.1.1/", "block link-local")
    blocked("https://10.0.0.5/v1", "block private 10/8")
    blocked("https://192.168.1.1/v1", "block private 192.168/16")
    blocked("https://172.16.5.1/v1", "block private 172.16/12")
    # Loopback is always allowed (local one-click: Ollama / LM Studio / MLX)
    allowed("https://127.0.0.1:11434/v1", "allow loopback https by default")
    allowed("http://localhost:11434/v1", "allow localhost http by default (no env flag)")
    allowed("http://127.0.0.1:1234/v1", "allow LM Studio loopback by default")
    allowed("http://127.0.0.1:8080/v1", "allow MLX loopback by default")
    blocked("http://api.openai.com/v1", "block remote http")
    blocked("ftp://example.com/", "block non-http scheme")
    blocked("https://user:pass@evil.com/v1", "block credentials in URL")
    blocked("", "block empty url")

    allowed("https://api.openai.com/v1", "allow public https")
    allowed("https://api.groq.com/openai/v1", "allow groq https")

    # Non-loopback private still blocked; remote http still blocked
    os.environ["ALLOW_LOCAL_HTTP"] = "1"
    allowed("http://localhost:11434/v1", "allow localhost http when flag set")
    allowed("http://127.0.0.1:11434/v1", "allow 127.0.0.1 http when flag set")
    blocked("http://10.0.0.5/v1", "still block private http even with ALLOW_LOCAL_HTTP")
    blocked("http://example.com/v1", "still block remote http even with ALLOW_LOCAL_HTTP")

    # Private ranges when explicitly allowed
    os.environ["ROUTISM_ALLOW_PRIVATE_URLS"] = "1"
    os.environ["ALLOW_LOCAL_HTTP"] = "0"
    allowed("https://10.0.0.5/v1", "allow private https when ROUTISM_ALLOW_PRIVATE_URLS=1")
    # Metadata / link-local stay blocked even when private is allowed.
    blocked("https://169.254.169.254/", "metadata still blocked with private allowed")
    blocked("https://169.254.0.1/", "link-local still blocked with private allowed")

    # DNS resolve path: force resolve for a public name (if network available)
    os.environ["ROUTISM_ALLOW_PRIVATE_URLS"] = "0"
    os.environ["ROUTISM_SSRF_RESOLVE"] = "1"
    try:
        validate_worker_base_url("https://example.com/")
        check("resolve public hostname ok", True)
    except SSRFBlocked as e:
        # Offline environments may fail resolution — still pass if error is not
        # a false private-block (empty resolve is allowed by design).
        check("resolve public hostname ok", "resolves to blocked" not in str(e), str(e))

    # ------------------------------------------------------------------ crypto
    print("\n--- BYOK crypto ---")
    reset_key_cache()
    os.environ.pop("ROUTISM_FERNET_KEY", None)
    os.environ.pop("ROUTISM_SECRETS_KEY", None)
    os.environ.pop("ROUTISM_DISABLE_LOCAL_FERNET", None)
    # Local installs auto-create data/local_fernet.key when env is unset
    check("auto local key material available", has_key_material())
    auto_enc = encrypt_secret("sk-auto-local")
    check("auto local encrypt works", is_encrypted(auto_enc), auto_enc[:20])
    check("auto local decrypt works", decrypt_secret(auto_enc) == "sk-auto-local")

    os.environ["ROUTISM_DISABLE_LOCAL_FERNET"] = "1"
    reset_key_cache()
    check("no key material when local disabled", not has_key_material())
    try:
        encrypt_secret("sk-test")
        check("encrypt without key raises when disabled", False)
    except CryptoKeysError:
        check("encrypt without key raises when disabled", True)
    os.environ.pop("ROUTISM_DISABLE_LOCAL_FERNET", None)
    reset_key_cache()

    key = generate_fernet_key()
    # validate generate_fernet_key produces usable Fernet material
    Fernet(key.encode("ascii"))
    os.environ["ROUTISM_FERNET_KEY"] = key
    reset_key_cache()
    check("has key material with FERNET", has_key_material())

    secret = "sk-test-placeholder-not-a-real-key"
    enc = encrypt_secret(secret)
    check("ciphertext has enc:v1: prefix", is_encrypted(enc), enc[:20])
    check("ciphertext != plaintext", enc != secret)
    check("roundtrip decrypt", decrypt_secret(enc) == secret)
    check("resolve_api_key decrypts", resolve_api_key(enc) == secret)
    check("idempotent re-encrypt", encrypt_secret(enc) == enc)
    check("legacy plaintext passthrough", decrypt_secret("sk-plain") == "sk-plain")
    check("resolve None", resolve_api_key(None) is None)
    check("resolve empty", resolve_api_key("") == "")

    # Wrong key fails hard for encrypted values
    os.environ["ROUTISM_FERNET_KEY"] = generate_fernet_key()
    reset_key_cache()
    try:
        decrypt_secret(enc)
        check("wrong key raises", False)
    except CryptoKeysError:
        check("wrong key raises", True)

    # PBKDF2 path from ROUTISM_SECRETS_KEY
    os.environ.pop("ROUTISM_FERNET_KEY", None)
    os.environ["ROUTISM_SECRETS_KEY"] = "dev-passphrase-not-for-prod"
    reset_key_cache()
    check("has key material with SECRETS_KEY", has_key_material())
    enc2 = encrypt_secret("nvapi-abc")
    check("pbkdf2 roundtrip", decrypt_secret(enc2) == "nvapi-abc")

    # Same passphrase re-derives same key (decrypt still works after cache reset)
    reset_key_cache()
    check("pbkdf2 stable after cache reset", decrypt_secret(enc2) == "nvapi-abc")

    # ------------------------------------------------------------------ management hook (import-level)
    print("\n--- management hook ---")
    import inspect
    from routism import management as mgmt

    src = inspect.getsource(mgmt.post_pool)
    check("post_pool calls validate_worker_base_url", "validate_worker_base_url" in src)
    check("post_pool encrypts api_key", "encrypt_secret" in src)
    check("SSRFBlocked imported", hasattr(mgmt, "SSRFBlocked") or "SSRFBlocked" in inspect.getsource(mgmt))

    # Functional: invalid base_url -> 400 via FastAPI HTTPException
    from fastapi import HTTPException
    from routism.management import WorkerIn, post_pool

    os.environ["ROUTISM_ALLOW_PRIVATE_URLS"] = "0"
    os.environ["ALLOW_LOCAL_HTTP"] = "0"
    os.environ["ROUTISM_SSRF_RESOLVE"] = "0"
    bad = WorkerIn(
        id="evil-meta",
        provider="test",
        base_url="https://169.254.169.254/v1",
        model="x",
    )
    try:
        post_pool(bad)
        check("post_pool rejects metadata URL with 400", False)
    except HTTPException as e:
        check(
            "post_pool rejects metadata URL with 400",
            e.status_code == 400 and "base_url" in str(e.detail).lower(),
            f"status={e.status_code} detail={e.detail}",
        )
    except Exception as e:
        # FileNotFoundError path should not run before SSRF check
        check(
            "post_pool rejects metadata URL with 400",
            False,
            f"unexpected {type(e).__name__}: {e}",
        )

    print(f"\n=== result: {passed} passed, {failed} failed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
