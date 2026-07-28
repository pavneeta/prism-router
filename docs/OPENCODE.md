# Use with OpenCode

Point [OpenCode](https://opencode.ai) at Prism Router so agent turns go through intelligence-aware, cache-aware routing.

## Architecture

```text
OpenCode  --OpenAI-compatible-->  Prism Router (:4000/v1)  --LiteLLM-->  Providers
                                  model: auto
                                  X-Session-Id
```

Provider API keys live on the **gateway** (`.env`), not in OpenCode.

## Prerequisites

1. Prism Router running locally (or reachable URL):

```bash
cd prism-router   # or Model-Router
source .venv/bin/activate
# Live:
model-router
# Or dry-run while wiring:
# MODEL_ROUTER_DRY_RUN=true model-router
```

2. OpenCode installed:

```bash
brew install anomalyco/tap/opencode
# or: curl -fsSL https://opencode.ai/install | bash
# or: npm i -g opencode-ai
```

Confirm: `opencode --version`

## Project config (recommended)

This repository ships [`opencode.json`](../opencode.json) at the project root. OpenCode loads it when you start OpenCode **from that directory**.

| Setting | Value |
| --- | --- |
| Provider id | `model-router` |
| Model id in UI | `model-router/auto` |
| API `model` field | often `auto` (prefix stripped; gateway accepts it) |
| `baseURL` | `http://127.0.0.1:4000/v1` |
| `X-Session-Id` | `opencode-local` (session affinity) |
| `apiKey` | `unused` (gateway does not need a real OpenCode-side key) |

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "model-router/auto",
  "provider": {
    "model-router": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Model-Router",
      "options": {
        "baseURL": "http://127.0.0.1:4000/v1",
        "apiKey": "unused",
        "streaming": false,
        "headers": {
          "X-Session-Id": "opencode-local"
        }
      },
      "models": {
        "auto": {
          "name": "Auto (cache-aware route)"
        }
      }
    }
  }
}
```

Copy this file into any other repo where you want the same wiring, and adjust `baseURL` if the gateway is remote.

## Optional global config

To use Prism Router outside this repo, merge the `provider.model-router` block into `~/.config/opencode/opencode.json`. **Back up first:**

```bash
mkdir -p ~/.config/opencode
cp ~/.config/opencode/opencode.json ~/.config/opencode/opencode.json.bak.$(date +%Y%m%d) 2>/dev/null || true
```

Do not overwrite an existing global file blindly.

## Auth

If OpenCode prompts for credentials:

```bash
opencode auth login
# Other → model-router → enter any non-empty key (e.g. unused)
```

Live OpenAI / Anthropic / Fireworks keys stay in the **gateway** `.env`.

## Run

```bash
# Terminal 1 — gateway
cd prism-router && source .venv/bin/activate && model-router

# Terminal 2 — OpenCode (from project with opencode.json)
cd prism-router
opencode
```

In the TUI, confirm model **model-router/auto** (`/models` if needed).

Non-interactive smoke (if your OpenCode build supports it):

```bash
opencode run "Reply with exactly: pong" -m model-router/auto --auto
```

## Verify without OpenCode

Simulate what OpenCode sends:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: opencode-local' \
  -d '{
    "model": "auto",
    "temperature": 0,
    "messages": [{"role": "user", "content": "Hello from OpenCode."}]
  }' | python -m json.tool
```

Check `model_router.decision.selected_model` and the assistant content.

## Streaming

OpenCode often uses `stream: true`. Prism Router speaks OpenAI-compatible SSE. Project config sets `"streaming": false` when you prefer non-stream requests; either mode is supported by the gateway.

## Tips for agent sessions

- Keep a **stable** `X-Session-Id` per OpenCode workspace/session so affinity preserves provider prompt caches.  
- Prefer `temperature: 0` for cacheable retries.  
- Use `/v1/router/explain` while tuning prompts and floors.  

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md#opencode-cannot-reach-the-gateway).
