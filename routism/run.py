"""P0.E — dev server launcher.

Run with the conda interpreter to avoid the homebrew-python re-exec issue that
some `uvicorn` binaries trigger:
    python3 -m routism.run
"""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv_files() -> None:
    """Load .env then .env.local (gitignored secrets) without requiring python-dotenv."""
    root = Path(__file__).resolve().parent.parent
    for name in (".env", ".env.local"):
        p = root / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def main() -> None:
    _load_dotenv_files()
    # Ensure data dir exists for keys / fernet
    data = os.environ.get("ROUTISM_DATA_DIR", "").strip()
    if data:
        Path(data).mkdir(parents=True, exist_ok=True)
    import uvicorn
    from .server import app

    host = os.environ.get("ROUTISM_HOST", "127.0.0.1")
    port = int(os.environ.get("ROUTISM_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
