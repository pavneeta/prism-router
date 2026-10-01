# Using Prism Router with Cursor

Prism Router is an OpenAI-compatible gateway. Point Cursor (or any harness) at your **local** or **self-hosted** base URL — not provider keys in the client when the gateway holds them.

## Local

```bash
cp .env.example .env   # provider keys + optional MODEL_ROUTER_DRY_RUN=true
model-router             # http://127.0.0.1:4000
```

In Cursor / OpenCode-style config, set:

- **Base URL:** `http://127.0.0.1:4000/v1`
- **Model:** `model-router/auto` or `auto`

See [docs/OPENCODE.md](docs/OPENCODE.md) and root [opencode.json](opencode.json).

## Internet-facing gateway

Set `MODEL_ROUTER_API_KEYS` on the server and send `Authorization: Bearer <client-key>` from the harness. See [docs/SECURITY.md](docs/SECURITY.md) and [docs/RAILWAY.md](docs/RAILWAY.md).

## Docs map

| Topic | Doc |
| --- | --- |
| Install & API | [docs/USAGE.md](docs/USAGE.md) |
| Deploy | [docs/RAILWAY.md](docs/RAILWAY.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Open-source checklist | [docs/internal/OPEN_SOURCE.md](docs/internal/OPEN_SOURCE.md) |

Never commit `.env` or paste provider keys into chat — rotate if leaked ([SECURITY.md](SECURITY.md)).
