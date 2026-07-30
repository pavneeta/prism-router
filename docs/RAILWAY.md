# Deploy Prism Router API on Railway

The **API gateway** (FastAPI + LiteLLM) deploys on [Railway](https://railway.com). The **marketing site + docs UI** stay on Vercel (`website/` → [prism-router-ten.vercel.app](https://prism-router-ten.vercel.app)).

## Public base URL

**Production:** [https://prism-router-production.up.railway.app](https://prism-router-production.up.railway.app)

```bash
export OPENAI_API_BASE="https://prism-router-production.up.railway.app/v1"
# OpenAI-compatible clients: model auto  or  model-router/auto
curl -sS "https://prism-router-production.up.railway.app/health"
curl -sS "https://prism-router-production.up.railway.app/ready"
curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "content-type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"ping"}]}'
# Streaming (SSE): add "stream": true and use curl -N
```

Streaming (`stream: true` on `/v1/chat/completions`) works on Railway the same as locally. Affinity remains per-replica (see checklist).

## Production checklist

1. **Replicas:** production runs **2** Railway replicas behind the same public URL (`prism-router-production.up.railway.app`). Railway does **not** guarantee sticky sessions — prompt-cache affinity and session task memory are **in-memory per process**, so cache/affinity may miss when a request lands on the other replica (routing still works). Shared Redis (or equivalent) is the follow-up for cross-replica affinity.
2. **Dry-run / mirror:** `MODEL_ROUTER_DRY_RUN=false`, `MODEL_ROUTER_MIRROR_MODE=false` unless intentionally shadow-evaling (~2× spend).
3. **Provider keys only:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FIREWORKS_API_KEY` (+ optional Together/Groq). No client `OPENAI_API_BASE` on the service.
4. **Telemetry path:** ephemeral FS — use `/tmp/model-router/telemetry.jsonl` (Dockerfile default). Writes fail soft; requests still succeed.
5. **Health:** Railway `healthcheckPath=/health`; use `/ready` for config load checks.
6. **Rate limits:** prefer Railway/edge limits; optional `MODEL_ROUTER_RATE_LIMIT_RPM` is in-process only (per replica).
7. **CORS:** set `MODEL_ROUTER_CORS_ORIGINS` only if browser clients call the API (comma-list or `*`).

## Required environment variables (names only)

Set these as Railway **service variables** (never commit values):

| Variable | Notes |
| --- | --- |
| `OPENAI_API_KEY` | Provider |
| `ANTHROPIC_API_KEY` | Provider |
| `FIREWORKS_API_KEY` | Provider (or `FIREWORKS_AI_API_KEY`) |
| `TOGETHER_API_KEY` / `GROQ_API_KEY` | Optional |
| `MODEL_ROUTER_DRY_RUN` | `false` for live routing |
| `MODEL_ROUTER_MIRROR_MODE` | `false` in production |
| `MODEL_ROUTER_HOST` | `0.0.0.0` |
| `MODEL_ROUTER_TELEMETRY_PATH` | e.g. `/tmp/model-router/telemetry.jsonl` |
| `MODEL_ROUTER_CONFIG_DIR` | `/app/config` (Dockerfile default) |
| `MODEL_ROUTER_PUBLIC_BASE` | Optional; production public URL (for self-base scrub) |
| `MODEL_ROUTER_CORS_ORIGINS` | Optional allowlist or `*` |
| `MODEL_ROUTER_RATE_LIMIT_RPM` | Optional in-process RPM; `0` = off |

Railway injects `PORT`; the [`Dockerfile`](../Dockerfile) maps it to `MODEL_ROUTER_PORT`. Container runs as non-root `app` (uid 10001).

## Deploy overview

Repo includes [`Dockerfile`](../Dockerfile) and [`railway.toml`](../railway.toml) (healthcheck on `/health`, restart on failure).

Install the [Railway CLI](https://docs.railway.com/cli) (agent-aware install):

```bash
curl -fsSL agents.railway.com | sh
source "$HOME/.railway/env"   # or restart the shell
railway whoami
```

Auth options:

| Method | When |
| --- | --- |
| `railway login` | Interactive / local |
| `RAILWAY_API_TOKEN` | Account/workspace token (CI or agents) |
| `RAILWAY_TOKEN` | **Project** token (scoped to one project) |

```bash
# Prefer account token for first-time project create:
export RAILWAY_API_TOKEN=...   # Railway → Account → Tokens — never commit

cd /path/to/prism-router
railway init -n prism-router   # once: create/link project
railway add                    # or use existing service
railway variables set MODEL_ROUTER_DRY_RUN=false MODEL_ROUTER_HOST=0.0.0.0
# set provider keys from a local .env without echoing:
#   railway variables set OPENAI_API_KEY=... ANTHROPIC_API_KEY=... FIREWORKS_API_KEY=...

railway up --detach
railway domain                 # generate public *.up.railway.app host
```

You can also ask the Railway agent after CLI setup: `railway agent -p "Deploy this Dockerfile service and expose /health"`.

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
curl -sS "https://<host>/ready"
```

## Follow-ups

- Shared Redis (or equivalent) for session affinity / local prompt cache across replicas.
- Hard rate limits at the Railway edge / CDN in front of the public host.

## Related

- Two paths (hosted + local): [USAGE.md](USAGE.md)
- CI / GHCR / Vercel: [CI.md](internal/CI.md)
- Keys: [SECURITY.md](SECURITY.md)
