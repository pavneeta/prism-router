# Prism Router (Model-Router)

**Intelligence-aware, cache-aware inference routing** for agent harnesses and high-volume multi-task workloads.

Prism Router sits in front of your model providers (via [LiteLLM](https://github.com/BerriAI/litellm)). It classifies each request, picks the cheapest model that still clears an **intelligence floor** for that task, and keeps multi-turn sessions sticky so **prompt caches** stay warm.

> **North-star metric:** lower **$/task completion** without giving up accuracy, intelligence, or turn latency.

Repo: [github.com/pavneeta/prism-router](https://github.com/pavneeta/prism-router)

**Live site:** [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app)

License: **Apache-2.0** · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

---

## Why this exists

Teams move to open or mid-tier models to cut spend, then either:

- overspend on frontier models for every turn, or  
- under-provision and lose task accuracy on hard coding / agent work.

Prism Router uses **public benchmarks** (DeepSWE, SWE-bench, Terminal-Bench, Artificial Analysis, Arena) plus **cache-aware cost** so you route by *task*, not by habit.

---

## Features

| Capability | What you get |
| --- | --- |
| Task-aware routing | Heuristic classifier + `easy`/`hard` → intelligence floor → min effective $ |
| Benchmark seed | DeepSWE / SWE-bench / Terminal-Bench / AA / Arena ([docs/BENCHMARKS.md](docs/BENCHMARKS.md)) |
| Cache-aware | Session affinity (`X-Session-Id`) and provider cache hints; local exact caching is opt-in |
| Drop-in API | OpenAI `POST /v1/chat/completions` (+ streaming) and Anthropic `POST /v1/messages` |
| Providers | Together.ai (default open-weight backend), Fireworks, OpenAI, Anthropic, and anything LiteLLM supports |
| Harness-friendly | Works with OpenCode, Hermes, HolmesGPT, and any OpenAI-compatible client |
| Sessions | `X-Session-Id` task memory + `GET /v1/router/sessions/{id}` rollups |

---

## Quick start

### Run locally

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add provider keys to .env (see below)
model-router           # local example: http://127.0.0.1:4000

# Dry-run (routing only, no provider spend)
# MODEL_ROUTER_DRY_RUN=true model-router

# Explain a route without starting the gateway
model-router why "Write a Python function that merges two lists."

# Write harness presets (placeholder host + local 127.0.0.1 example)
model-router init opencode
```

```bash
# After the gateway is up — local example:
export OPENAI_API_BASE="http://127.0.0.1:4000/v1"
# Self-hosted / deployed:
# export OPENAI_API_BASE="https://<your-prism-host>/v1"

curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: demo-1' \
  -d '{
    "model": "auto",
    "messages": [{"role": "user", "content": "Write a Python hello world."}]
  }' | python -m json.tool
```

Use model id `model-router/auto` or `auto`. Responses include a `model_router` block with classification and the selected model.

Self-host the gateway (local CLI, Docker, or [Railway](docs/RAILWAY.md)), then point every client at **your** OpenAI-compatible `/v1` — `https://<your-prism-host>/v1` or `$OPENAI_API_BASE`. `http://127.0.0.1:4000/v1` is only the local example after `model-router` is running. Set `MODEL_ROUTER_API_KEYS` on any internet-facing deploy. Full guide: [docs/USAGE.md](docs/USAGE.md).

---

## Documentation

| Doc | Contents |
| --- | --- |
| **[Usage guide](docs/USAGE.md)** | Local install, config, API, telemetry |
| **[Deploy (Railway)](docs/RAILWAY.md)** | Container deploy, env vars, replicas |
| **[Troubleshooting](docs/TROUBLESHOOTING.md)** | Common errors and fixes |
| **[OpenCode](docs/OPENCODE.md)** | Point OpenCode at Prism Router |
| **[Hermes](docs/HERMES.md)** | Point Nous Hermes Agent at Prism Router |
| **[HolmesGPT](docs/HOLMESGPT.md)** | Point HolmesGPT (CNCF SRE agent) at Prism Router |
| [Together.ai](docs/TOGETHER.md) | Default open-weight mappings and setup |
| [Benchmarks](docs/BENCHMARKS.md) | Score provenance and task mapping |
| [Security](docs/SECURITY.md) | Key rotation and secret handling |
| [Contributing](CONTRIBUTING.md) | Dev setup and PR expectations |
| [Architecture](docs/internal/ARCHITECTURE.md) | System design (GitHub) |
| [CI](docs/internal/CI.md) | Pytest CI, monthly benchmarks, GHCR release (GitHub) |
| [A/B notes](docs/internal/AB_ANTHROPIC_VS_FIREWORKS.md) | Anthropic vs Fireworks session snapshot (GitHub) |

---

## Provider keys (gateway-side)

Put **provider** keys in **`.env`** (gitignored) or host secrets. Never commit them. Never put them in harness config if the gateway already holds them. If a key was ever pasted into chat, **rotate it** ([SECURITY.md](SECURITY.md) / [docs/SECURITY.md](docs/SECURITY.md)).

For **internet-facing** gateways, also set **client** keys:

```bash
MODEL_ROUTER_API_KEYS=pr_your_long_random_client_key
MODEL_ROUTER_RATE_LIMIT_RPM=60
```

Clients then send `Authorization: Bearer …` or `X-Api-Key` (OpenAI-compatible).

```bash
FIREWORKS_API_KEY=...
TOGETHER_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
MODEL_ROUTER_DRY_RUN=false
```

Enable deployments in [`config/models.yaml`](config/models.yaml). Intelligence floors and cache knobs live in [`config/policy.yaml`](config/policy.yaml).

---

## Harness examples (one-liners)

Self-host Prism, then point each client at **your** `/v1` (`https://<your-prism-host>/v1` or `$OPENAI_API_BASE`). Local snippets below assume `model-router` is already running.

**OpenCode** — set `baseURL` to `https://<your-prism-host>/v1` with model `model-router/auto`. The shipped [`opencode.json`](opencode.json) is a **local example** (`http://127.0.0.1:4000/v1`) for after `model-router` is up. See [docs/OPENCODE.md](docs/OPENCODE.md).

**Hermes** — in `~/.hermes/config.yaml`:

```yaml
model:
  default: auto
  provider: custom
  base_url: https://<your-prism-host>/v1
  api_key: unused
```

Local example: `base_url: http://127.0.0.1:4000/v1`. See [docs/HERMES.md](docs/HERMES.md).

**HolmesGPT** — OpenAI-compatible env + `openai/auto`:

```bash
export OPENAI_API_BASE=https://<your-prism-host>/v1
# Local example after model-router: export OPENAI_API_BASE=http://127.0.0.1:4000/v1
export OPENAI_API_KEY=none
holmes ask "what pods are failing?" --model=openai/auto
```

See [docs/HOLMESGPT.md](docs/HOLMESGPT.md) and [`examples/holmesgpt/`](examples/holmesgpt/).

---

## Tests

```bash
pytest
python scripts/cpt_routing_eval.py
```

## Benchmark refresh (CI)

Monthly GitHub Action refreshes [`config/benchmarks.yaml`](config/benchmarks.yaml) from public leaderboards (DeepSWE JSON where available) and opens a PR. No provider API keys. See [docs/internal/CI.md](docs/internal/CI.md).

```bash
python scripts/update_benchmarks.py --dry-run -v
```

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
