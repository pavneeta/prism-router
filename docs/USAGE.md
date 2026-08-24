# Usage guide

Two ways to use **Prism Router**. See also [RAILWAY.md](RAILWAY.md), [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md), [HOLMESGPT.md](HOLMESGPT.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [SECURITY.md](SECURITY.md).

**Live marketing site:** [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) · **Docs:** [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs)

---

## Option A — Hosted API (Railway)

Use the production gateway (demo). Point any OpenAI-compatible client at:

| | |
| --- | --- |
| **Gateway** | [https://prism-router-production.up.railway.app](https://prism-router-production.up.railway.app) |
| **API base** | `https://prism-router-production.up.railway.app/v1` |
| **Model** | `auto` or `model-router/auto` |
| **Client auth** | If `MODEL_ROUTER_API_KEYS` is set on the gateway, pass `Authorization: Bearer <key>` or `X-Api-Key` |

```bash
export OPENAI_API_BASE="https://prism-router-production.up.railway.app/v1"
# export OPENAI_API_KEY="your-prism-client-key"  # when client auth is enabled

curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY:-unused}" \
  -H "X-Session-Id: demo-1" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Write a Python hello world."}]
  }' | python -m json.tool
```

Deploy steps, env var **names**, and Railway CLI notes: **[RAILWAY.md](RAILWAY.md)**. Marketing/docs stay on Vercel; only the FastAPI service runs on Railway. For your own production traffic, prefer self-hosting (Option B or your own Railway project) with `MODEL_ROUTER_API_KEYS` set.

---

## Option B — Run locally

Clone the repo, add provider keys, and run the gateway on your machine.

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add provider keys — never commit .env
model-router           # http://127.0.0.1:4000
```

```bash
export OPENAI_API_BASE="http://127.0.0.1:4000/v1"

curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-1" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Write a Python hello world."}]
  }' | python -m json.tool
```

Dry-run (routing only, no provider spend):

```bash
MODEL_ROUTER_DRY_RUN=true model-router
# or
model-router --dry-run
```

### Mirror mode (shadow eval)

For **passthrough** requests (customer picks an explicit model), Prism still returns that model’s answer, and in the background also runs **`auto`** selection + completion. Both sides are appended to JSONL for offline comparison. Optionally a small LLM judges the pair.

```bash
model-router --mirror-mode --mirror-judge
# or env:
# MODEL_ROUTER_MIRROR_MODE=true
# MODEL_ROUTER_MIRROR_JUDGE=true
# MODEL_ROUTER_MIRROR_PATH=logs/mirror.jsonl
# MODEL_ROUTER_MIRROR_JUDGE_MODEL=openai/gpt-4o-mini
```

- Client latency ≈ primary only (shadow is background).
- Skipped when the client already requests `auto` / `*/auto`, or `stream=true`.
- Response `model_router.mirror` confirms logging path.
- Summarize later: `python scripts/mirror_summary.py`

**Cost:** each mirrored request can be ~2× provider spend (+ judge ≈ 3×). Keep off in production unless evaluating.

---

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-compatible (+ `stream` SSE) |
| `POST /v1/messages` | Anthropic Messages-compatible (non-stream MVP) |
| `POST /v1/router/explain` | Classification + selection without calling a model |
| `GET /v1/router/sessions/{id}` | Per-session telemetry rollup (tokens, $, cache hits) |
| `GET /health` | Liveness |

Use model `model-router/auto` or `auto`. Responses include a `model_router` block with classification and the selected model.

### Sessions

Send a stable `X-Session-Id` header (or `session_id` on `/v1/router/explain`) to enable:

1. **Session affinity** — sticky model so provider prompt caches stay warm  
2. **Session task memory** — weak follow-ups keep the prior task type until a confident drift  
3. **Rollups** — `GET /v1/router/sessions/{id}` returns request count, latency, tokens, estimated/actual $, frontier delta, and estimated cache savings  

Provider cache hints (when `prompt_cache_enabled` and the model supports caching): Anthropic gets `cache_control`; OpenAI/Fireworks get a session `prompt_cache_key`. Fireworks also receives `x-session-affinity` (KV cache is replica-local — keep a stable session id, and prefer a single gateway replica for affinity).

Fireworks tip: provider `cached_tokens` show up reliably on multi-turn / identical retries with a long shared prefix (a few thousand tokens in practice). Very short prompts may stay at `cached_tokens: 0` even with affinity hints.

### Streaming

OpenAI-compatible streaming is supported on chat completions. Send `"stream": true`; the gateway returns `text/event-stream` (SSE) with OpenAI-style `data:` chunks and a terminal `data: [DONE]`.

```bash
curl -N -sS "$OPENAI_API_BASE/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-stream" \
  -d '{
    "model": "auto",
    "stream": true,
    "messages": [{"role": "user", "content": "Count to three."}]
  }'
```

Works for both **auto** (`auto` / `model-router/auto`) and **passthrough** (explicit provider model ids). Clients such as the OpenAI SDK (`stream=True`), OpenCode, Hermes, and HolmesGPT can enable streaming the same way.

**Caveats**

| Topic | Behavior |
| --- | --- |
| Anthropic `/v1/messages` | Streaming is **not** implemented (`stream: true` → `400`). Use `/v1/chat/completions` for SSE. |
| Local exact-match cache | Bypassed when `stream: true` (non-stream only). |
| Mirror mode | Shadow auto-eval is skipped for streamed requests. |
| Dry-run | Returns synthetic SSE (`[dry-run] …`) so clients can exercise `stream: true` without provider spend. |
| Railway replicas | Streaming works with multiple replicas; session affinity / prompt-cache stickiness remains in-memory per process (same as non-stream). |

## Config

| File | Role |
| --- | --- |
| [`config/models.yaml`](../config/models.yaml) | Enable deployments / LiteLLM model ids |
| [`config/policy.yaml`](../config/policy.yaml) | Intelligence floors, cache knobs, `fireworks_hide_thinking` |
| [`config/benchmarks.yaml`](../config/benchmarks.yaml) | Cost + public benchmark sources |

Restart the gateway after YAML edits.

### Fireworks thinking / CoT

Reasoning models on Fireworks can dump chain-of-thought into visible `content`. Prism Router defaults `fireworks_hide_thinking: true` in `policy.yaml`, which sends:

- `thinking: {"type": "disabled"}`

(Fireworks rejects combining this with `reasoning_effort`.) Set `fireworks_hide_thinking: false` if you want CoT in the response. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [Fireworks chat completions](https://docs.fireworks.ai/api-reference/post-chatcompletions).

## Telemetry

- Per-request JSONL: path from `MODEL_ROUTER_TELEMETRY_PATH` (default `logs/telemetry.jsonl`)
- Mirror shadow-eval JSONL: `MODEL_ROUTER_MIRROR_PATH` (default `logs/mirror.jsonl`) when `--mirror-mode` is on
- Per-session rollups: `logs/session_rollups.jsonl` + HTTP `GET /v1/router/sessions/{id}`
- Offline CPT-style distribution: `python scripts/cpt_routing_eval.py`

## Smoke tests

```bash
pytest
python scripts/hermes_smoke.py   # local gateway must be up on :4000
```
