# Usage guide

Install, configure, and call **Prism Router**. See also [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md), [HOLMESGPT.md](HOLMESGPT.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [SECURITY.md](SECURITY.md), [CI.md](CI.md).

**Live marketing site:** [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) · **Docs:** [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs)

## Install & run

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add provider keys — never commit .env
model-router           # http://127.0.0.1:4000
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

### Streaming

`POST /v1/chat/completions` with `"stream": true` returns OpenAI-style SSE. Anthropic `/v1/messages` streaming is not implemented yet — use chat completions for streams.

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
python scripts/hermes_smoke.py   # gateway must be up on :4000
```
