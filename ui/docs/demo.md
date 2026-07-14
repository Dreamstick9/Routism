# Routism UI — End-to-end demo

Repeatable path with **no terminal commands** once both servers are running.

## Start both servers
```bash
# terminal 1 — backend (FastAPI on :8000)
cd .
python3 -m routism.run

# terminal 2 — dashboard (Next.js on :3000)
cd ./ui
npm run dev
```
Open http://localhost:3000.

## Frame 1 — Empty Providers (0/5)
```
+------------------------------+
| Routism      Providers Plan  |
|------------------------------|
| Providers       0/5 connected|
|                              |
| [ Add a provider form ]      |
|                              |
|  --------------------------  |
|  No providers connected yet. |
|  --------------------------  |
+------------------------------+
```

## Frame 2 — Two providers added (2/5, both reachable)
Add via the form (no YAML edit):
- `ollama_local` — provider `local`, base_url `http://localhost:11434/v1`, model `qwen2.5:0.5b` → Test → `reachable`
- `openai_cloud` — provider `openai`, base_url `https://api.openai.com/v1`, model `gpt-4o-mini`, api_key_env `OPENAI_API_KEY` → Test → `reachable` (requires key in env; skip if absent and document as optional)
```
+------------------------------+
| Routism      Providers Plan  |
|------------------------------|
| Providers       2/5 connected|
|  [ollama_local] local        |
|  http://localhost:11434/v1   |
|  qwen2.5:0.5b  reachable     |
|  [Test] [Remove]             |
|  [openai_cloud] openai       |
|  https://api.openai.com/v1   |
|  gpt-4o-mini  reachable      |
|  [Test] [Remove]             |
+------------------------------+
```

## Frame 3 — Complex query on /plan (multi-step cards)
Go to **Plan**, enter:
> Design a REST API for a todo app, then write pytest tests for it.

Run. Step cards appear top to bottom, each with its own worker_id + output, then a **Final answer** card. Cost chip shows non-zero in/out tokens.
```
+------------------------------+
| Routism      Providers Plan  |
|------------------------------|
| Plan                         |
|  [textarea...]  [Run plan]   |
|  mode: complex  steps: 2     |
|  in: 18 / out: 42            |
|  +------------------------+  |
|  | Step 1  ollama_local   |  |
|  | Design a REST API...   |  |
|  | <output>               |  |
|  +------------------------+  |
|  +------------------------+  |
|  | Step 2  ollama_local   |  |
|  | Write pytest tests...  |  |
|  | <output>               |  |
|  +------------------------+  |
|  == Final answer ==========  |
|  <synthesized answer>        |
+------------------------------+
```

## Isolation check
The `/api/plan` trace exposes `access_list` per step. A step whose `access_list`
is empty (or lists only prior step indices) proves it only saw allowed context —
this is the architectural guarantee against orchestration collapse.

## Persistence
Refresh the page — the pool re-renders from `routism.yaml` (backend persists
provider config). No re-add needed.

## Caveat
The cloud (OpenAI) step requires `OPENAI_API_KEY` in the backend env. Without it,
demo Frame 2/3 with two *different* worker_ids is n/a; the Ollama-only single-provider
path still works and the multi-step card view is demonstrable if the pool has more
than one local worker.
