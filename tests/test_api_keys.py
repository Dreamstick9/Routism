#!/usr/bin/env python3
"""API keys store + HTTP routes (no login)."""
from __future__ import annotations
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def main() -> int:
    db = tempfile.mktemp(suffix="_keys.db")
    os.environ["ROUTISM_API_KEYS_PATH"] = db
    os.environ["ROUTISM_OPEN_LOCAL"] = "1"
    os.environ["ROUTISM_ALLOW_ANON_LOOPBACK"] = "1"
    os.environ.pop("ROUTISM_REQUIRE_API_KEY", None)
    import routism.api_keys as ak
    ak.reset_api_key_store_for_tests()
    store = ak.get_api_key_store()
    meta, raw = store.create("t")
    assert raw.startswith("rtm_")
    assert store.is_valid(raw)
    assert store.revoke(meta.id)
    assert not store.is_valid(raw)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(ak.router)
    c = TestClient(app)
    r = c.post("/v1/keys", json={"name": "a"})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert secret.startswith("rtm_")
    r2 = c.get("/v1/keys")
    assert r2.status_code == 200
    print("PASS api_keys")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
