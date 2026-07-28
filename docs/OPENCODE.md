# OpenCode ↔ Model-Router

Point OpenCode at the local Model-Router gateway so chat completions use intelligence-aware routing (`model-router/auto`).

## Prerequisites

1. Model-Router running (dry-run or live):

```bash
cd Model-Router
source .venv/bin/activate
export MODEL_ROUTER_DRY_RUN=true   # omit / set false when provider API keys are in .env
model-router                       # http://0.0.0.0:4000
```

2. OpenCode installed (any one):

```bash
brew install anomalyco/tap/opencode
# or: curl -fsSL https://opencode.ai/install | bash
# or: npm i -g opencode-ai
```

## Project config (preferred)

This repo includes [`opencode.json`](../opencode.json) at the project root. OpenCode loads project config when you run it from this directory.

| Setting | Value |
| --- | --- |
| Provider id | `model-router` |
| Model picker id | `model-router/auto` |
| API `model` field sent | `auto` (accepted by gateway `auto_model_ids`) |
| `baseURL` | `http://127.0.0.1:4000/v1` |
| Session header | `X-Session-Id: opencode-local` (affinity / prompt-cache stickiness) |
| `streaming` | `false` (OpenCode usually streams; MVP also accepts `stream:true` via SSE replay) |

Contents:

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

## Optional global config

Only if you want this provider outside this repo. **Back up first** if `~/.config/opencode/opencode.json` already exists:

```bash
mkdir -p ~/.config/opencode
cp ~/.config/opencode/opencode.json ~/.config/opencode/opencode.json.bak.$(date +%Y%m%d) 2>/dev/null || true
# merge the provider block above into ~/.config/opencode/opencode.json
```

Do not silently overwrite an existing global file; merge the `provider.model-router` block.

## Auth note

`apiKey` is set to `"unused"` in project config because the local gateway does not require a real key in dry-run. For live mode, keys belong on the **gateway** side (`.env` / LiteLLM), not in OpenCode.

If OpenCode still prompts for provider auth, run `opencode auth login`, choose **Other**, pick `model-router`, and enter any non-empty key (e.g. `unused`).

## Run

```bash
# terminal 1 — gateway
cd Model-Router && source .venv/bin/activate && MODEL_ROUTER_DRY_RUN=true model-router

# terminal 2 — OpenCode from this project
cd Model-Router
opencode
# or non-interactive smoke (if your build supports it):
# opencode run "Say hi in one sentence." --model model-router/auto
```

In the TUI, confirm the model is **model-router/auto** (`/models` if needed).

## Curl stand-in (what OpenCode sends)

OpenCode’s OpenAI-compatible adapter POSTs to `/v1/chat/completions` with model id `auto` (provider prefix stripped):

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Session-Id: opencode-local' \
  -d '{
    "model": "auto",
    "temperature": 0,
    "messages": [{"role":"user","content":"Hello from OpenCode."}]
  }' | python3 -m json.tool
```

## Stop gateway

```bash
# if started in foreground: Ctrl-C
# if you know the port:
lsof -ti :4000 | xargs kill
```
