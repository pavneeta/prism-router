# Use with Cursor

Point [Cursor](https://cursor.com) at **your** Prism Router `/v1` so agent turns go through intelligence-aware, cache-aware routing. Cursor talks to any OpenAI-compatible base URL.

`model-router ui` is a **terminal** getting-started CLI (not a web `/ui`). Use it locally to inspect status, explain a route, or send a smoke request.

## Prerequisites

Self-host the gateway first (local CLI or your container), then point Cursor at **your** `/v1`:

| | |
| --- | --- |
| **Self-hosted / deployed** | `https://<your-prism-host>/v1` (see [RAILWAY.md](RAILWAY.md)) |
| **Local example** | `http://127.0.0.1:4000/v1` — only after `model-router` is running |

```bash
# Local example — Terminal 1
cd prism-router
source .venv/bin/activate
model-router
# Or dry-run while wiring: MODEL_ROUTER_DRY_RUN=true model-router
```

Together.ai is the default open-weight backend. Put `TOGETHER_API_KEY` (and any other provider keys) in the **gateway** `.env`, not in Cursor.

## Project preset

From any project directory:

```bash
model-router init cursor
```

That writes `.cursor/prism-router.md` with a paste-ready OpenAI-compatible snippet (placeholder `https://<your-prism-host>/v1`, model `auto`). For the local example after `model-router` is up, use `http://127.0.0.1:4000/v1`.

## Cursor settings

In Cursor Settings → Models (OpenAI-compatible / custom base URL):

| Setting | Value |
| --- | --- |
| **Base URL** | `https://<your-prism-host>/v1` (local example: `http://127.0.0.1:4000/v1`) |
| **Model** | `auto` or `model-router/auto` |
| **API key** | `unused` locally; on a public gateway, send `MODEL_ROUTER_API_KEYS` as `Authorization: Bearer …` |

Provider keys stay on the gateway. Never paste them into Cursor chat — rotate if leaked ([SECURITY.md](SECURITY.md)).

## Check a route before you send

```bash
model-router why "Write a Python function that merges two lists."
model-router ui --status
```

See [USAGE.md](USAGE.md) for install, the `ui` / `why` / `init` CLI, and the OpenAI-compatible API.
