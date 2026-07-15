# Routism

**Self-hosted multi-model orchestration for coding agents.**

Routism is an OpenAI-compatible Chat Completions server. You point Hermes, Cursor, Continue, or any OpenAI SDK at it with model id `routism-ultra`. On each request it does **not** forward blindly to a single model: a **Conductor** builds a task DAG, fans work across your configured model endpoints (up to five), scores candidates, optionally re-plans weak layers, and synthesizes one assistant reply.

- Single-machine install (Docker + CLI). MIT license.
- No cloud multi-tenant accounts, OAuth, or billing in this tree.
- Agents keep **tool execution** on their side; Routism generates text only (`tools` / tool schemas in the request are ignored, not rejected).

| | |
|--|--|
| Public model id | `routism-ultra` |
| Chat | `POST /v1/chat/completions` (stream + non-stream) |
| Models | `GET /v1/models` |
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| Spec | [docs/API.md](docs/API.md) · [docs/OPENAI_COMPAT.md](docs/OPENAI_COMPAT.md) |

---

## Why this exists

Coding agents already speak OpenAI Chat Completions. Connecting an agent to one local or cloud model is easy; **getting better answers by combining several models** is not—each agent would need its own planner, fan-out, scoring, and merge.

Routism is that layer:

1. Stable **OpenAI-shaped API** so agents do not change.
2. **User-owned worker pool** (any OpenAI-compatible base URL + model; local or cloud; max 5).
3. **Conductor pipeline** that treats those workers as black boxes: plan → assign → execute layers → score → merge → verify.

You care about **answer quality, latency budget, and control of keys/endpoints**—not about internal slogans. Internally, planning and scoring use dedicated local models (via Ollama on the host); generation uses whatever you registered as workers. That split is an implementation detail so the orchestrator can stay stable while your generation pool changes.

---

## Architecture (request path)

```
Agent (Cursor / Hermes / SDK)
        │  POST /v1/chat/completions  model=routism-ultra
        ▼
┌───────────────────────────────────────────────────────────┐
│  routism/ (FastAPI)                                       │
│  auth (optional rtm_ key) → openai_compat → orchestrator  │
└────────────────────────────┬──────────────────────────────┘
                             │
                             ▼
┌───────────────────────────────────────────────────────────┐
│  routism_orch/  Conductor                                 │
│                                                           │
│  1. Plan     eng-thinker (local Ollama)                   │
│              → ConductorPlan: subtasks, tags, DAG edges   │
│  2. Assign   match subtask tags → worker capabilities     │
│  3. Execute  topological layers; fan_out to workers       │
│              (HTTP chat to each worker base_url/model)    │
│  4. Score    eng-verifier: absolute 0–10 style scores     │
│              eng-judge2: optional pairwise tie-break      │
│  5. Replan   if layer mean score < floor (≤1 replan)      │
│  6. Merge    synthesize + verify_and_refine                │
│  7. Return   one assistant message (optional SSE)        │
└────────────────────────────┬──────────────────────────────┘
                             │
           ┌─────────────────┼─────────────────┐
           ▼                 ▼                 ▼
     Worker A            Worker B           Worker C
     (your URLs)         (≤5 total)         …
```

### Components

| Package | Role |
|---------|------|
| `routism/` | HTTP API, API keys, management/pool, health probes, crypto for worker secrets, OpenAI envelope |
| `routism_orch/` | Conductor plan/assign/execute/score/merge, trajectories, eval harness |
| `ui/` | Next.js dashboard (providers, keys, orchestration view, metrics) |
| `routism_cli/` | `routism` CLI: setup, doctor, start/stop, pull orchestration models |
| `routism_orch/orch.yaml` | **Internal** model registry for planner/verifier/judge (not the user pool) |
| `routism.yaml` | **Your** worker pool (from `routism.example.yaml` or dashboard writes) |

### Orchestration models (local Ollama)

Configured in [`routism_orch/orch.yaml`](routism_orch/orch.yaml). Current defaults:

| Internal id | Role | Ollama tag (default) |
|-------------|------|----------------------|
| `eng-thinker` | Plan DAG, expand work orders, help synthesize | `qwen2.5:7b` |
| `eng-verifier` | Score candidates for correctness / consistency | `qwen2.5:7b` |
| `eng-judge2` | Pairwise A/B when needed | `deepseek-r1:1.5b` |

These are **not** listed as selectable chat models for the agent. The agent always sees `routism-ultra`. Docker does not ship weights; the API reaches host Ollama via `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`).

### Worker pool (your models)

- Cap **5** OpenAI-compatible endpoints (Ollama, MLX, LM Studio, Groq, OpenRouter, etc.).
- Tags (`code`, `reasoning`, `math`, …) feed assignment from the capability registry in `orch.yaml`.
- Secrets encrypted at rest (auto local Fernet under data dir).
- Health probes are honest: HTTP 401 is **not** treated as healthy.

With **one** worker, Routism still runs Conductor overhead (plan/score/merge around a single backend). With **2–5**, fan-out and merge are meaningful.

---

## Evidence & benchmarks

### Northstar live comparison (shipped artifact)

Harness: `python -m routism_orch.eval_conductor`  
Artifact: [`eval_results/NORTHSTAR_SHIP_EVIDENCE.json`](eval_results/NORTHSTAR_SHIP_EVIDENCE.json)  
Recorded: **2026-07-13**, `kind: live_all`, `SHIP: YES`.

**Protocol (honest scope):**

- **4** tasks from `eval_seed_northstar.json` (`ns_api_pipeline`, `ns_rate_limit`, `ns_code_explain`, `ns_research_chain`).
- Score scale: **absolute 0–10 multipart** (not a leaderboard-normalized public bench).
- Comparison: Conductor final answer vs **best solo worker** on the same task (strict beat; ties not counted as wins).
- Timeout: 600s per run configuration.
- Workers in that run (ids → models at the time):

  | Worker id | Model string |
  |-----------|----------------|
  | `groq` | `openai/gpt-oss-120b` |
  | `nvidia-nim` | `z-ai/glm-5.2` |
  | `kilo` | `nvidia/nemotron-3-ultra-550b-a55b:free` |
  | `opencode` | `hy3-free` |

**Headline metrics** (`metrics` in the ship evidence file):

| Metric | Value |
|--------|------:|
| Tasks `n` | 4 |
| Conductor win rate vs max solo worker | **75%** (3/4) |
| Mean Conductor score | **8.392** |
| Mean max-worker score | **7.864** |
| Mean delta (conductor − max worker) | **+0.529** |
| `strict_beat` | true |
| `synthetic_margin` | false |
| Offline recovery fill-in | **0** markers |

**Per-task** (from `rows`):

| Task | Conductor | Best worker | Winner | Δ |
|------|----------:|------------:|--------|--:|
| `ns_api_pipeline` | 6.132 | 9.539 (`groq`) | worker | −3.407 |
| `ns_rate_limit` | 9.626 | 8.982 (`groq`) | conductor | +0.644 |
| `ns_code_explain` | 9.240 | 6.388 (`opencode`) | conductor | +2.852 |
| `ns_research_chain` | 8.571 | 6.546 (`groq`) | conductor | +2.025 |

**How to read this:** On this seed and this pool, Conductor **won 3 of 4** against the strongest single worker, with a clear loss on a pipeline-style API task where a strong solo cloud model scored higher. This is **not** SWE-bench / MMLU. It is an **in-repo regression northstar** used to ship the Conductor path. Reproduce or extend with:

```bash
python -m routism_orch.eval_conductor \
  --mode all \
  --seed routism_orch/eval_seed_northstar.json \
  --limit 4 \
  --timeout 600
```

Related dumps: `eval_results/northstar_ship.json`, `northstar_atomic_all.json`, `northstar_absolute.json`. Pairwise-only scales and rescored variants also exist; ship gate for absolute multipart is the evidence file above.

### What the product optimizes for

- **Beat max solo worker** on multi-step / multi-skill tasks when the pool has complementary strengths.
- **Degrade** when a layer scores poorly (replan once, merge fallbacks—see `orchestrate_conductor.py`).
- **Observability**: trajectories under data, `GET /v1/metrics`, dashboard orchestration view.

---

## Install & run

### Recommended: CLI

Requires **Docker** (API + UI) and **Ollama on the host** (orchestration models).

```bash
git clone https://github.com/Dreamstick9/Routism.git Routism
cd Routism

./install.sh          # installs `routism` onto PATH (~/.local/bin)
routism               # interactive setup (default)
```

| Command | Purpose |
|---------|---------|
| `routism` | Full interactive setup |
| `routism setup -y` | Non-interactive |
| `routism doctor` | Docker, Ollama, model tags, endpoints |
| `routism start` / `stop` | Compose stack |
| `routism status` / `logs` | Containers |
| `routism open` | Open dashboard |
| `routism pull-engine` | `ollama pull` for tags in `orch.yaml` |

From repo without install: `./bin/routism`.

After setup:

1. Dashboard **Providers** → register workers.  
2. **API keys** → create `rtm_…` (copy once).  
3. Point the agent:

```bash
export OPENAI_BASE_URL="http://localhost:8000/v1"
export OPENAI_API_KEY="rtm_…"
# model: routism-ultra
# client timeout: 300–600 seconds (multi-step)
```

### Docker only

If Ollama + orchestration models are already present:

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |

Volume `routism-data` → `/data` (keys DB, Fernet key, optional bootstrap key).

### Local development (no Docker)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp routism.example.yaml routism.yaml   # optional
python -m routism.run                  # :8000

cd ui && npm ci && npm run dev          # :3000
```

`NEXT_PUBLIC_ROUTISM_API` must be reachable from the **browser**.

---

## HTTP surface (summary)

Full tables: [docs/API.md](docs/API.md).

### OpenAI-compatible

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $ROUTISM_KEY" \
  -H 'content-type: application/json' \
  -d '{
    "model": "routism-ultra",
    "messages": [{"role": "user", "content": "Explain rate limiting in one paragraph."}]
  }'
```

- `stream: true` → SSE `chat.completion.chunk`, ends with `data: [DONE]`.
- Multi-turn messages are folded into the orchestrator prompt.
- Errors: OpenAI-style `{ "error": { "message", "type", "code" } }`.

### API keys

```bash
curl -s http://localhost:8000/v1/keys
curl -s -X POST http://localhost:8000/v1/keys \
  -H 'content-type: application/json' \
  -d '{"name":"hermes"}'
curl -s -X DELETE http://localhost:8000/v1/keys/key_…
```

Keys hashed in `$ROUTISM_DATA_DIR/api_keys.db`. Loopback defaults allow key management without a prior key; public deploy → `ROUTISM_REQUIRE_API_KEY=1`.

### Management / pool

| Method | Path |
|--------|------|
| GET/POST | `/v1/management/pool` |
| DELETE | `/v1/management/pool/{id}` |
| GET | `/v1/management/health/{id}` |
| GET | `/v1/management/local/{provider}/models` |
| POST | `/v1/management/fetch-models` |
| POST | `/v1/run` | Conductor SSE for dashboard |

Remote pool mutation: loopback or `MANAGEMENT_API_KEY`.

### Ops

| Path | Purpose |
|------|---------|
| `GET /v1/health` | Aggregate worker probes |
| `GET /v1/metrics` | Pool / last eval snapshot for UI |

---

## Configuration

See [`.env.example`](.env.example).

| Variable | Default | Meaning |
|----------|---------|---------|
| `ROUTISM_DATA_DIR` | `./data` | SQLite keys, Fernet, bootstrap |
| `ROUTISM_API_KEY` | — | Optional fixed bootstrap `rtm_…` |
| `ROUTISM_REQUIRE_API_KEY` | `0` | Require Bearer on protected routes |
| `ROUTISM_OPEN_LOCAL` | `1` | Key CRUD open on loopback |
| `ROUTISM_ALLOW_ANON_LOOPBACK` | `1` | Chat without key from loopback |
| `ROUTISM_FERNET_KEY` / `ROUTISM_SECRETS_KEY` | auto | Encrypt worker secrets |
| `MANAGEMENT_API_KEY` | unset | Remote management; else loopback |
| `NEXT_PUBLIC_ROUTISM_API` | `http://localhost:8000` | Browser → API |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | API → host Ollama |

**Do not** expose `:8000` to the internet without API keys enforced.

Worker file: `routism.yaml` (example: `routism.example.yaml`). Orchestration registry: `routism_orch/orch.yaml`.

---

## System requirements (practical)

| Piece | Need |
|-------|------|
| Docker | API + UI containers |
| Ollama on host | Planner / verifier / judge models |
| Disk | Images + multi-GB model pulls (e.g. 7B-class tags) |
| RAM | **16 GB** practical minimum; **32 GB** if workers are also large local models |
| Agent timeout | **300–600 s** (multi-step) |

Control plane alone is moderate; **model weights dominate** cost and latency.

---

## Repository layout

```text
routism/              # FastAPI server, workers, keys, management
routism_orch/         # Conductor, eval, orch.yaml, seeds
routism_cli/          # CLI implementation
ui/                   # Dashboard
docs/                 # API + OpenAI agent notes
eval_results/         # Northstar and related dumps
tests/                # unit + public safety
docker-compose.yml
Dockerfile
install.sh · bin/routism
archive/              # historical research/gates (not required to run)
```

---

## Agents (Cursor, Hermes, Continue, SDKs)

| Setting | Value |
|---------|--------|
| Base URL | `http://localhost:8000/v1` |
| API key | `rtm_…` |
| Model | `routism-ultra` |
| Timeout | ≥ 300–600 s |

Tools remain in the agent harness. Routism returns text (and stream chunks).

---

## Security & public safety

- Worker API keys: Fernet at rest under data dir.  
- SSRF controls on outbound worker URLs (public HTTPS or loopback).  
- **Never commit:** `.env`, real `routism.yaml`, `data/`, personal absolute paths.

```bash
python3 tests/test_public_safety.py
```

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Weak / empty answers | Workers registered and healthy? Pool non-empty? |
| 401 | Missing/revoked key or strict require-key mode |
| Long hangs | Raise agent timeout; inspect `routism logs` / trajectories |
| UI blank / wrong API | `NEXT_PUBLIC_ROUTISM_API` from browser network |
| Conductor fails plan | Ollama up? `routism doctor` / `routism pull-engine` |
| Provider add fails | Fernet key; SSRF (HTTPS or loopback only) |

---

## License

[MIT](LICENSE).

---

## References

- Conductor execution: `routism_orch/orchestrate_conductor.py`, `conductor.py`, `judge.py`, `synthesize.py`
- OpenAI adapter: `routism/openai_compat.py`, `routism/server.py`
- Eval: `python -m routism_orch.eval_conductor`
- Metrics helpers: `routism_orch/northstar_metrics.py`
- Background research (Sakana-style coordinator literature, not runtime): `ARCHITECTURE.md`, `archive/`
