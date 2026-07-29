# Deploy Prism Router API on Railway

The **API gateway** (FastAPI + LiteLLM) deploys on [Railway](https://railway.com). The **marketing site + docs UI** stay on Vercel (`website/` → [prism-router-ten.vercel.app](https://prism-router-ten.vercel.app)).

## Public base URL

After the first successful deploy, Railway assigns a public HTTPS host (typically `*.up.railway.app`). Clients should set:

```bash
export OPENAI_API_BASE="https://<your-service>.up.railway.app/v1"
# OpenAI-compatible clients:
#   model: auto   or   model-router/auto
curl -sS "$OPENAI_API_BASE/../health"
curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "content-type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"ping"}]}'
```

Update this doc (and the website sync) with the concrete host once it is stable. Do **not** set `OPENAI_API_BASE` on the Railway **service itself** to the Railway URL (or to `localhost:4000`) — that confuses LiteLLM when the gateway calls providers.

## Required environment variables (names only)

Set these as Railway **service variables** (never commit values):

| Variable | Notes |
| --- | --- |
| `OPENAI_API_KEY` | Provider |
| `ANTHROPIC_API_KEY` | Provider |
| `FIREWORKS_API_KEY` | Provider (or `FIREWORKS_AI_API_KEY`) |
| `TOGETHER_API_KEY` / `GROQ_API_KEY` | Optional |
| `MODEL_ROUTER_DRY_RUN` | `false` for live routing |
| `MODEL_ROUTER_HOST` | `0.0.0.0` |
| `MODEL_ROUTER_TELEMETRY_PATH` | e.g. `/tmp/telemetry.jsonl` (ephemeral FS) |
| `MODEL_ROUTER_CONFIG_DIR` | `/app/config` (Dockerfile default) |

Railway injects `PORT`; the [`Dockerfile`](../Dockerfile) maps it to `MODEL_ROUTER_PORT`. Clear any self-referential `OPENAI_API_BASE` on the service.

Optional: `MODEL_ROUTER_MIRROR_MODE` (keep `false` in production unless shadow-eval is intentional — ~2× spend).

## Deploy overview

Repo includes [`Dockerfile`](../Dockerfile) and [`railway.toml`](../railway.toml) (healthcheck on `/health`).

```bash
# Account/workspace token from Railway → Account → Tokens
export RAILWAY_TOKEN=...   # CLI env only — never commit

railway login   # or rely on RAILWAY_TOKEN
railway init    # once: create/link project + service (e.g. prism-router)
railway variables set MODEL_ROUTER_DRY_RUN=false MODEL_ROUTER_HOST=0.0.0.0
# set provider keys from a local .env without echoing:
#   railway variables set OPENAI_API_KEY=... ANTHROPIC_API_KEY=... FIREWORKS_API_KEY=...

railway up --detach
# Generate a public domain in the Railway dashboard (Networking → Public Networking)
# or: railway domain
```

Prefer building from the repo Dockerfile on `main`. Alternatively pull the GHCR image from tag `v*` (`ghcr.io/pavneeta/prism-router:latest`) if you configure an image-based service instead of a GitHub build.

## Redeploy

```bash
git push origin main
railway up --detach
# or trigger Redeploy from the Railway dashboard
```

Smoke-test:

```bash
curl -sS "https://<host>/health"
```

## Related

- Local usage: [USAGE.md](USAGE.md)
- CI / GHCR / Vercel: [CI.md](CI.md)
- Keys: [SECURITY.md](SECURITY.md)
