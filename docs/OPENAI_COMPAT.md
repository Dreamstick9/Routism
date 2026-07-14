# OpenAI-compatible setup (agents)

Use Routism as a **Chat Completions backend**. Tools stay in Hermes / Cursor / your harness.

| Setting | Value |
|---------|--------|
| Base URL | `http://127.0.0.1:8000/v1` |
| API key | `rtm_…` from **API keys** page or bootstrap file |
| Model | `routism-ultra` |
| Timeout | **300–600 seconds** |

```bash
export OPENAI_BASE_URL="http://127.0.0.1:8000/v1"
export OPENAI_API_KEY="rtm_…"
```

Full HTTP surface: [API.md](./API.md).
