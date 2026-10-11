# Usage guide

Run **Prism Router** locally or deploy your own container. See also [RAILWAY.md](RAILWAY.md), [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md), [HOLMESGPT.md](HOLMESGPT.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [SECURITY.md](SECURITY.md).

**Live marketing site:** [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) · **Docs:** [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs)

---

## Point your client

Prism is a **self-hosted** OpenAI-compatible gateway. After you run it (local CLI or your container), point every client at **your** `/v1` — not a public Prism API.

| Setup | API base |
| --- | --- |
| **Self-hosted / deployed** | `https://<your-prism-host>/v1` — or set `OPENAI_API_BASE` |
| **Local example** | `http://127.0.0.1:4000/v1` — only after `model-router` is running |
| **Model** | `auto` or `model-router/auto` |
| **Client auth** | On public URLs, set `MODEL_ROUTER_API_KEYS` and pass `Authorization: Bearer <key>` or `X-Api-Key` |

```bash
export OPENAI_API_BASE="https://<your-prism-host>/v1"
# Local example (after `model-router` is running):
# export OPENAI_API_BASE="http://127.0.0.1:4000/v1"

curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: demo-1" \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Write a Python hello world."}]
  }' | python -m json.tool
```

Deploy your own host with Docker / **[RAILWAY.md](RAILWAY.md)** (or any container platform). On any public URL, set `MODEL_ROUTER_API_KEYS`.

---

## Install the CLI

`model-router` and `prism` ship on the [v0.3.0 GitHub Release](https://github.com/pavneeta/prism-router/releases/tag/v0.3.0) (wheel + sdist). There is no PyPI package yet.

```bash
pip install https://github.com/pavneeta/prism-router/releases/download/v0.3.0/model_router-0.3.0-py3-none-any.whl
# or: pip install "git+https://github.com/pavneeta/prism-router.git@v0.3.0"
```

The GHCR image (`ghcr.io/pavneeta/prism-router:v0.3.0`) installs the same package and runs `model-router`.

```bash
model-router              # start the gateway
model-router ui           # terminal getting-started CLI (not a web /ui)
model-router ui --status  # gateway / local settings
model-router ui --why "Write a Python function that merges two lists."
# REPL commands: status / why / send / setup / quit
model-router why "..."    # explain a route (no daemon)
model-router init cursor  # also: opencode, hermes
```

## Run locally

Clone the repo, add provider keys, and run the gateway on your machine. Then use the **local example** base above.

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add provider keys — never commit .env
model-router           # local example: http://127.0.0.1:4000

# Explain classification + selected model (no daemon required)
model-router why "Write a Python function that merges two lists."
# alias: prism why "..."   or   python -m model_router.why "..."

# Interactive local getting-started CLI (does not start the gateway)
model-router ui
model-router ui --status
model-router ui --why "Write a Python function that merges two lists."

# Write harness presets into the current project
model-router init opencode   # opencode.json
model-router init cursor     # .cursor/prism-router.md paste note
model-router init hermes     # hermes-prism.snippet.yaml
```

`model-router` with no subcommand still starts the gateway. `model-router ui` is a terminal REPL (`status` / `why` / `send` / `setup` / `quit`). It reads local `/health` when a gateway is already up; otherwise it prints in-process settings and how to run `model-router` in another terminal. Pass `--start` only when you want this command to spawn a throwaway local gateway for the session.

---

## Config & environment

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
| `POST /v1/messages` | Anthropic Messages-compatible (**non-stream**; use `/v1/chat/completions?stream=true` for SSE) |
| `POST /v1/router/explain` | Classification + selection without calling a model |
| `GET /v1/router/sessions/{id}` | Per-session telemetry rollup (tokens, $, cache hits) |
| `GET /v1/router/metrics/usage` | In-process token usage by session / model / provider |
| `POST /v1/router/feedback` | Pass/fail outcome; updates a fail-soft task×model EWMA nudge |
| `GET /health` | Liveness |
| `GET /ready` | Readiness (config load). Includes `benchmarks_snapshot_date` so operators can confirm auto is using the latest merged catalog. |

Use model `model-router/auto` or `auto`. Responses include a `model_router` block with classification and the selected model.

### Sessions

Send a stable `X-Session-Id` header (or `session_id` on `/v1/router/explain`) to enable:

1. **Session affinity** — sticky model so provider prompt caches stay warm  
2. **Session task memory** — weak follow-ups keep the prior task type until a confident drift  
3. **Rollups** — `GET /v1/router/sessions/{id}` returns request count, latency, tokens, estimated/actual $, frontier delta, and estimated cache savings  

Provider cache hints (when `prompt_cache_enabled` and the model supports caching): Anthropic gets `cache_control`; OpenAI/Fireworks get a session `prompt_cache_key`. Fireworks also receives `x-session-affinity` (KV cache is replica-local — keep a stable session id, and prefer a single gateway replica for affinity).

Fireworks tip: provider `cached_tokens` show up reliably on multi-turn / identical retries with a long shared prefix (a few thousand tokens in practice). Very short prompts may stay at `cached_tokens: 0` even with affinity hints.

### Usage metrics

`GET /v1/router/metrics/usage` exposes in-process token usage aggregated by session, selected model, and provider type (`openai` / `anthropic` / `fireworks` / …). Optional query filters: `session_id`, `model`, `provider`.

```bash
curl -sS "$OPENAI_API_BASE/router/metrics/usage?session_id=demo-1"
# Local example: http://127.0.0.1:4000/v1/router/metrics/usage?session_id=demo-1
```

Response includes `totals`, `by_session`, `by_model`, `by_provider`, plus `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens` (when the provider reports them), `request_count`, `est_cost_usd`, and `actual_cost_usd`. Streaming completions record usage when the provider sends it on a final chunk (OpenAI-, Together-, and Fireworks-compatible streams request `stream_options.include_usage`).

When client auth or public mode is enabled, this global endpoint requires
`X-Admin-Api-Key` matching `MODEL_ROUTER_ADMIN_API_KEY`.

**Replica caveat:** metrics are **per gateway process**. With Railway `numReplicas=2` (or any multi-replica deploy), each replica only reports its own traffic; totals are not cluster-wide.

**Cross-replica affinity:** set `MODEL_ROUTER_REDIS_URL` (and install optional `redis` extra) so session affinity is shared across replicas. Optional `shared_local_cache_enabled: true` in `config/policy.yaml` mirrors the local exact-match cache in Redis too.

### Outcome feedback

`POST /v1/router/feedback` appends `{session_id, outcome: pass|fail, task_hint?, selected_model?, notes?}` to `MODEL_ROUTER_FEEDBACK_PATH` (default `logs/feedback.jsonl`). Missing `task_hint` / `selected_model` are filled from the session's last turn when available.

The same events feed an in-memory EWMA of **task × model pass rate**. That EWMA is a **soft cost nudge** after public intelligence floors — it never replaces floors in `policy.yaml`. Fail-soft: missing data is a no-op.

### Why a prompt routed that way

```bash
model-router why "From the text extract JSON with keys name and port only: ..."
```

Prints task, difficulty (`easy`/`hard`), confidence, selected model, estimated $, and reason. Same policy as the gateway (`require_credentials=False` so it works offline). `POST /v1/router/explain` is the HTTP equivalent when a server is already running.

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
| Timeouts | Streams have configurable idle and total deadlines; disconnects close the upstream iterator. |
| Retry | Non-stream requests retry one retryable timeout/429/5xx once. Streams are never replayed after bytes are emitted; auth/permission failures are never retried. |
| Railway replicas | Streaming works with multiple replicas. Set `MODEL_ROUTER_REDIS_URL` for shared session affinity across replicas. |

## Config

| File | Role |
| --- | --- |
| [`config/models.yaml`](../config/models.yaml) | Enable deployments / LiteLLM model ids |
| [`config/policy.yaml`](../config/policy.yaml) | Intelligence floors, `hard_accuracy_bump` (hard codegen/debug/tools only), cache knobs, `fireworks_hide_thinking` |
| [`config/benchmarks.yaml`](../config/benchmarks.yaml) | Cost + public benchmark sources |

Restart the gateway after YAML edits.

Easy coding / debug / tool turns keep the public floors (cheap MiniMax/DeepSeek remain eligible). **Hard** turns of those types add `hard_accuracy_bump` (default `0.05`). Chat, extract, summary, and creative never get the bump.

Optional LLM second-pass classify is off by default (`MODEL_ROUTER_LLM_CLASSIFY=false`). When enabled, it only runs if heuristic confidence is below `0.7`, uses a tight timeout, and falls back to the heuristic on any failure. No extra model download is required.

### Fireworks thinking / CoT

Reasoning models on Fireworks can dump chain-of-thought into visible `content`. Prism Router defaults `fireworks_hide_thinking: true` in `policy.yaml`, which sends:

- `thinking: {"type": "disabled"}`

(Fireworks rejects combining this with `reasoning_effort`.) Set `fireworks_hide_thinking: false` if you want CoT in the response. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) and [Fireworks chat completions](https://docs.fireworks.ai/api-reference/post-chatcompletions).

## Telemetry

- Per-request JSONL: path from `MODEL_ROUTER_TELEMETRY_PATH` (default `logs/telemetry.jsonl`)
- Mirror shadow-eval JSONL: `MODEL_ROUTER_MIRROR_PATH` (default `logs/mirror.jsonl`) when `--mirror-mode` is on
- Per-session rollups: `logs/session_rollups.jsonl` + HTTP `GET /v1/router/sessions/{id}`
- In-process usage metrics: `GET /v1/router/metrics/usage` (per-replica; see [Usage metrics](#usage-metrics))
- Offline CPT-style distribution: `python scripts/cpt_routing_eval.py`

## Smoke tests

```bash
pytest
python scripts/hermes_smoke.py   # local gateway must be up on :4000
```
