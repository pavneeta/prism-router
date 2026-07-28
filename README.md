# Model-Router

Intelligence-aware **cache-aware** AI inference router: pick the right model for each task using benchmarks to minimize **$/task completion** without sacrificing intelligence or accuracy — including prompt-cache savings across turns.

Built on **Python + LiteLLM** (OpenAI-compatible gateway). Model-Router decides *which* model; LiteLLM calls the provider.

## Status

- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Benchmark provenance: [docs/BENCHMARKS.md](docs/BENCHMARKS.md)
- Requirements: [Model router requirements.md](Model%20router%20requirements.md)
- MVP scaffold: classifier, **multi-source public benchmarks** (DeepSWE, SWE-bench, Terminal-Bench, Artificial Analysis, Arena), intelligence-floor policy, prompt caching, JSONL telemetry

## Quick start

```bash
cd Model-Router
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Optional: add OPENAI_API_KEY (or other provider keys) to .env
```

### Dry-run (no provider calls)

```bash
export MODEL_ROUTER_DRY_RUN=true
model-router
# or: uvicorn model_router.gateway:app --host 0.0.0.0 --port 4000
```

### Explain a routing decision

```bash
curl -s http://127.0.0.1:4000/v1/router/explain \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "model-router/auto",
    "messages": [{"role":"user","content":"Write a Python function to merge two sorted lists."}]
  }' | python -m json.tool
```

### Chat completions (auto-route + session affinity)

Send `X-Session-Id` so multi-turn agent loops stick to the same model and keep provider prompt caches warm:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: agent-session-1' \
  -d '{
    "model": "model-router/auto",
    "temperature": 0,
    "messages": [{"role":"user","content":"Hello — keep it short."}]
  }' | python -m json.tool
```

Point any OpenAI SDK at the gateway:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key="unused")
client.chat.completions.create(
    model="model-router/auto",
    messages=[{"role": "user", "content": "Summarize: ..."}],
    extra_headers={"X-Session-Id": "agent-session-1"},
)
```

## How routing works

1. **Local prompt cache** — exact-match lookup **before** classify/route for deterministic retries (`temperature` 0/omitted; skipped when `stream=true`). TTLs come from [config/policy.yaml](config/policy.yaml).
2. **Classify** the request into a task type (`code_generation`, `general_chat`, …). Tools present is a signal (not a hard override) so harness coding turns still route as code.
3. **Filter** enabled models whose **derived** accuracy for that task clears the intelligence floor ([config/policy.yaml](config/policy.yaml)). Accuracies come from DeepSWE / SWE-bench / Terminal-Bench / AA / Arena ([docs/BENCHMARKS.md](docs/BENCHMARKS.md)).
4. **Pick** lowest **effective** $/request among eligible models, pricing **cached vs uncached** tokens and preferring **session affinity** when it preserves provider prompt-cache savings ([config/benchmarks.yaml](config/benchmarks.yaml)).
5. **Call** via LiteLLM (supports `stream=true` SSE); inject provider cache hints when the model supports prompt caching; update affinity + local cache; log tokens, $, cache layer, and Δ$ vs frontier to `logs/telemetry.jsonl`.

Enable OSS deployments in [config/models.yaml](config/models.yaml) once you have provider API keys.

### Streaming

```bash
curl -N http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"model-router/auto","stream":true,"messages":[{"role":"user","content":"Hi"}]}'
```

## Tests

```bash
pytest
# Offline CPT-style routing distribution (no network):
python scripts/cpt_routing_eval.py
```

## Layout

```text
docs/ARCHITECTURE.md
config/                 # policy, benchmarks (+ cache rates), deployments
src/model_router/       # gateway, classifier, cache-aware policy, prompt_cache, telemetry
tests/
```

## Roadmap (post-MVP)

- Anthropic Messages compatibility + native `cache_control` passthrough
- Prefix / semantic local prompt cache
- Tiny learned classifier + session awareness
- Online anonymized benchmark updates from harness ticks
- Cloud multi-replica gateway + shared affinity/cache store
- First-class harness adapters (Hermes, open-code, …)

## Benchmark refresh (CI)

Monthly GitHub Action refreshes `config/benchmarks.yaml` from public leaderboards and opens a PR. No provider API keys. See [docs/CI.md](docs/CI.md).

```bash
python scripts/update_benchmarks.py --dry-run -v
```

