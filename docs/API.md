# Routism API Reference

**Self-hosted installation.** No user accounts, OAuth, or billing.

Base URL (default): `http://127.0.0.1:8000`  
OpenAI prefix: `http://127.0.0.1:8000/v1`

---

## Authentication

| Mode | Behavior |
|------|----------|
| Bearer API key | `Authorization: Bearer rtm_…` |
| Loopback open (default) | Mutations & chat allowed without key from `127.0.0.1` when `ROUTISM_OPEN_LOCAL` / `ROUTISM_ALLOW_ANON_LOOPBACK` are on |
| Strict | `ROUTISM_REQUIRE_API_KEY=1` → key required |

Keys: hashed at rest in `$ROUTISM_DATA_DIR/api_keys.db`.

---

## OpenAI-compatible

### `GET /v1/models`

Returns `routism-ultra`.

### `POST /v1/chat/completions`

| Field | Notes |
|-------|--------|
| `model` | Use `routism-ultra` |
| `messages` | Standard chat messages; multi-turn folded into one prompt |
| `stream` | `true` → SSE `chat.completion.chunk` + `[DONE]` |
| `max_tokens` | Applied to final answer when set |
| `tools` / extras | **Ignored** (no 422) — tools stay in the agent |

Errors use OpenAI envelope: `{ "error": { "message", "type", "code" } }`.

---

## API keys

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/keys` | List active keys + `base_url` / `model` |
| POST | `/v1/keys` | Body `{ "name" }` → `{ key, secret }` once |
| DELETE | `/v1/keys/{id}` | Revoke |

---

## Management (worker pool)

Single-tenant pool in `routism.yaml` (cap 5).

| Method | Path | Auth |
|--------|------|------|
| GET | `/v1/management/pool` | open |
| POST | `/v1/management/pool` | loopback or `MANAGEMENT_API_KEY` |
| DELETE | `/v1/management/pool/{id}` | loopback or management key |
| GET | `/v1/management/health/{id}` | open |
| GET | `/v1/management/local/{provider}/models` | open |
| POST | `/v1/management/fetch-models` | open |
| POST | `/v1/management/ollama/start` | loopback / management key |

Worker body: `id`, `provider`, `base_url`, `model`, `tags`, optional `api_key`.

---

## Other

| Path | Purpose |
|------|---------|
| `GET /v1/health` | Aggregate worker probes |
| `GET /v1/metrics` | Pool / engine snapshot |
| `POST /v1/run` | Conductor SSE for dashboard |
| `GET /v1/settings` | Settings (management auth) |

---

## Environment

See [`.env.example`](../.env.example) and [README.md](../README.md).
