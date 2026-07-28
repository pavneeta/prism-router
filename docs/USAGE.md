# Usage guide

Install, configure, and call **Prism Router**. See also [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [SECURITY.md](SECURITY.md).

## Install & run

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # add provider keys — never commit .env
model-router           # http://127.0.0.1:4000
```

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/chat/completions` | OpenAI-compatible (+ `stream`) |
| `POST /v1/messages` | Anthropic Messages-compatible (non-stream) |
| `POST /v1/router/explain` | Classification + selection without calling a model |
| `GET /v1/router/sessions/{id}` | Per-session telemetry rollup |
| `GET /health` | Liveness |

Use model `model-router/auto` or `auto`. Send `X-Session-Id` for affinity + session task memory.

## Config

- [`config/models.yaml`](../config/models.yaml) — enable deployments  
- [`config/policy.yaml`](../config/policy.yaml) — intelligence floors, cache knobs  
- [`config/benchmarks.yaml`](../config/benchmarks.yaml) — cost + benchmark sources  

Restart the gateway after YAML edits.
