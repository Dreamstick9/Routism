# Routism

**Self-hosted, OpenAI-compatible multi-model orchestration for coding agents.**

Point Hermes, Cursor, Continue, or any OpenAI SDK at Routism. It runs a **Conductor** plan across your BYOK workers (Ollama, MLX, Groq, OpenAI-compatible APIs, …) and returns a single assistant answer.

- **No accounts / OAuth / billing** — single installation, ready to use  
- **API keys** (`rtm_…`) for agents  
- **MIT licensed**

| | |
|--|--|
| Model id | `routism-ultra` |
| Chat API | `POST /v1/chat/completions` |
| Models list | `GET /v1/models` |
| Docs | [docs/API.md](docs/API.md) · [docs/OPENAI_COMPAT.md](docs/OPENAI_COMPAT.md) |
| Showcase site | [showcase/](showcase/) — marketing page (`npm run dev` → http://localhost:3100) |

---

## One command: `routism`

Engine brains run on **host Ollama** (not inside Docker). The CLI checks Docker + Ollama, downloads engine models if needed, writes `.env`, and starts **API + UI**. Questions are asked as setup runs.

```bash
git clone https://github.com/Dreamstick9/Routism.git Routism
cd Routism

./install.sh          # once — installs `routism` on your PATH
routism               # interactive full setup (default — no extra args)
```

Bare `routism` **is** setup. You do **not** need `python3 -m routism_cli`.

| Command | What it does |
|---------|----------------|
| `routism` | Interactive full setup |
| `routism setup -y` | Non-interactive (scripts/CI) |
| `routism doctor` | Health checks only |
| `routism start` / `stop` | Start or stop API + UI |
| `routism status` / `logs` | Containers |
| `routism open` | Open http://localhost:3000 |
| `routism pull-engine` | Download engine models only |

Without install (from repo root): `./bin/routism`

Then in the dashboard: **Providers** → connect workers → **API keys** → create a key:

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="rtm_…"
# model: routism-ultra
# Client timeout: 300–600 seconds
```

---

## Quick start (Docker only)

If Ollama + engine models are already on the host:

```bash
git clone <your-fork-or-url> Routism
cd Routism

docker compose up --build
```

Wait until both services are up, then open:

| What | URL |
|------|-----|
| **Dashboard (UI)** | http://localhost:3000 |
| **API** | http://localhost:8000 |

The API container reaches host Ollama via `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`).

1. Open **http://localhost:3000** → **Providers** → connect Ollama or a cloud endpoint.  
2. **API keys** → create a key (copy the secret once).  
3. Point your agent at the API (snippet above).

First API boot may mint a bootstrap key into the Docker volume (`routism-data` → `/data/bootstrap_key.txt`).

---

## Local development (no Docker)

```bash
# API
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp routism.example.yaml routism.yaml   # optional pool
python -m routism.run                  # http://127.0.0.1:8000

# UI (another terminal)
cd ui && npm ci && npm run dev         # http://localhost:3000
```

Set `NEXT_PUBLIC_ROUTISM_API=http://localhost:8000` if needed.

---

## Features

- OpenAI Chat Completions shape (stream + non-stream)  
- Conductor multi-step orchestration (`routism_orch`)  
- Worker pool (≤5) via dashboard or YAML  
- Local one-click discovery: Ollama, LM Studio, MLX  
- Encrypted worker secrets at rest (auto local Fernet key)  
- Installation API keys with create / list / revoke  
- Honest health probes (401 ≠ healthy)

**Not included:** cloud multi-tenant SaaS, OAuth login, Stripe/credits, tool execution (tools stay in your agent).

---

## Configuration

See [`.env.example`](.env.example). Important variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ROUTISM_DATA_DIR` | `./data` | SQLite keys, Fernet key, bootstrap file |
| `ROUTISM_API_KEY` | — | Optional fixed bootstrap key (`rtm_…`) |
| `ROUTISM_REQUIRE_API_KEY` | `0` | `1` = require Bearer on protected routes |
| `ROUTISM_OPEN_LOCAL` | `1` | Create/list keys without prior key on loopback |
| `ROUTISM_ALLOW_ANON_LOOPBACK` | `1` | Chat without key from loopback |
| `ROUTISM_FERNET_KEY` / `ROUTISM_SECRETS_KEY` | auto | Encrypt worker API keys |
| `MANAGEMENT_API_KEY` | unset | Remote pool edits; unset = loopback only |
| `NEXT_PUBLIC_ROUTISM_API` | `http://localhost:8000` | Dashboard → API URL |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | API container → host Ollama (engine models) |

**Security:** Do not expose port 8000 to the internet without `ROUTISM_REQUIRE_API_KEY=1` and strong keys.

---

## API keys

```bash
# List
curl -s http://localhost:8000/v1/keys

# Create
curl -s -X POST http://localhost:8000/v1/keys \
  -H 'content-type: application/json' \
  -d '{"name":"hermes"}'

# Revoke
curl -s -X DELETE http://localhost:8000/v1/keys/key_…
```

On loopback with defaults, no Bearer is required for key management. On a public host, set `ROUTISM_REQUIRE_API_KEY=1`.

---

## Chat completions

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $ROUTISM_KEY" \
  -H 'content-type: application/json' \
  -d '{
    "model": "routism-ultra",
    "messages": [{"role": "user", "content": "Say hello in one sentence."}]
  }'
```

Streaming: `"stream": true` → SSE chunks ending with `data: [DONE]`.

Full reference: [docs/API.md](docs/API.md).

---

## Agents (Hermes, Cursor, etc.)

| Setting | Value |
|---------|--------|
| Base URL | `http://localhost:8000/v1` |
| API key | `rtm_…` |
| Model | `routism-ultra` |
| Timeout | **≥ 300–600 s** |

Routism ignores `tools` / tool schemas in the request body (no 422). **Tool use stays in the agent** — Routism only generates text via orchestration.

---

## Data & volumes

Docker Compose mounts `routism-data` → `/data`:

- `api_keys.db` — hashed API keys  
- `local_fernet.key` — encryption key for worker secrets  
- `bootstrap_key.txt` — first-boot key (if generated)

Pool config defaults to `routism.yaml` in the container (from `routism.example.yaml`). Mount your own file to persist workers.

---

## Project layout

```text
routism/           # FastAPI app, workers, management, keys
routism_orch/      # Conductor engine
ui/                # Next.js dashboard
docs/              # API + agent guides
Dockerfile         # API image
docker-compose.yml # API + UI
LICENSE            # MIT
```

Research notes and old gates live under `archive/` (not required to run).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Empty / weak answers | Providers connected? Pool healthy on dashboard? |
| 401 | Key revoked/missing; or `ROUTISM_REQUIRE_API_KEY=1` without Bearer |
| Provider add fails | Fernet key auto-creates under data/; check SSRF (public HTTPS or loopback) |
| Agent timeouts | Raise client timeout; Conductor is multi-step |
| UI can’t reach API | `NEXT_PUBLIC_ROUTISM_API` must be reachable **from the browser** |

---

## Publishing / public safety

**Do not commit** secrets or machine-local files:

- `.env`, `.env.local`
- `routism.yaml` (your real worker keys/pool)
- `data/` (API keys DB, Fernet key, bootstrap key)
- Absolute personal paths

Ship only product sources + `.env.example` + `routism.example.yaml`.  
Local secrets stay gitignored. Scan before push:

```bash
python3 tests/test_public_safety.py
```

## License

[MIT](LICENSE) — free to use, modify, and distribute.
