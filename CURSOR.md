# Using Prism Router with Cursor

Canonical guide: **[docs/CURSOR.md](docs/CURSOR.md)**.

Prism Router is an OpenAI-compatible gateway. Point Cursor at **your** `/v1` — not provider keys in the client when the gateway holds them.

```bash
model-router init cursor   # writes .cursor/prism-router.md
```

| Setup | Base URL | Model |
| --- | --- | --- |
| Self-hosted / deployed | `https://<your-prism-host>/v1` | `auto` |
| Local example (after `model-router`) | `http://127.0.0.1:4000/v1` | `auto` |

See [docs/USAGE.md](docs/USAGE.md), [docs/OPENCODE.md](docs/OPENCODE.md), and [docs/RAILWAY.md](docs/RAILWAY.md).

Never commit `.env` or paste provider keys into chat — rotate if leaked ([SECURITY.md](SECURITY.md)).
