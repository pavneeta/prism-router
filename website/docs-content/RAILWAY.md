# Deploy Prism Router API on Railway

The **API gateway** (FastAPI + LiteLLM) deploys on [Railway](https://railway.com). The **marketing site + docs UI** stay on Vercel (`website/` → [prism-router-ten.vercel.app](https://prism-router-ten.vercel.app)).

## Public base URL

After `railway domain` (or your custom domain), point clients at **your** service hostname — not `127.0.0.1:4000` (that is only the local `model-router` example):

```bash
export OPENAI_API_BASE="https://<your-service>.up.railway.app/v1"
# OpenAI-compatible clients: model auto  or  model-router/auto
curl -sS "https://<your-service>.up.railway.app/health"
curl -sS "https://<your-service>.up.railway.app/ready"
curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H "content-type: application/json" \
  -H "Authorization: Bearer ${OPENAI_API_KEY:-unused}" \
  -d '{"model":"auto","messages":[{"role":"user","content":"ping"}]}'
# Streaming (SSE): add "stream": true and use curl -N
```

Streaming (`stream: true` on `/v1/chat/completions`) works on Railway the same as locally. Affinity remains per-replica (see checklist).

## Production checklist

1. **Client auth (required for public URLs):** set `MODEL_ROUTER_API_KEYS` to one or more random client keys. Without this, anyone can spend your provider budget. Clients send `Authorization: Bearer …` or `X-Api-Key`.
2. **Replicas:** optional multi-replica behind one public URL (`railway.toml`). Railway does **not** guarantee HTTP sticky sessions. Set **`MODEL_ROUTER_REDIS_URL`** (Railway Redis plugin or external URL) so **session affinity** is shared across replicas. Install the Python `redis` package in your image (`pip install '.[redis]'` or add to Dockerfile). Session **task memory** and usage metrics remain per-replica unless you add a shared store later. Optional `shared_local_cache_enabled: true` in `config/policy.yaml` shares the local exact-match cache via Redis.
3. **Dry-run / mirror:** `MODEL_ROUTER_DRY_RUN=false`, `MODEL_ROUTER_MIRROR_MODE=false` unless intentionally shadow-evaling (~2× spend).
4. **Provider keys only on the service:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FIREWORKS_API_KEY` (+ optional Together/Groq). Do **not** set client `OPENAI_API_BASE` on the Railway service to its own URL.
5. **Telemetry path:** ephemeral FS — use `/tmp/model-router/telemetry.jsonl` (Dockerfile default). Writes fail soft; requests still succeed.
6. **Health:** Railway `healthcheckPath=/health`; use `/ready` for config load checks.
7. **Rate limits:** prefer Railway/edge limits; optional `MODEL_ROUTER_RATE_LIMIT_RPM` is in-process only (per replica).
8. **CORS:** set `MODEL_ROUTER_CORS_ORIGINS` only if browser clients call the API (comma-list or `*`).

## Required environment variables (names only)

Set these as Railway **service variables** (never commit values):

| Variable | Notes |
| --- | --- |
| `MODEL_ROUTER_API_KEYS` | **Client** keys (comma-separated). Set on public deploys |
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
| `MODEL_ROUTER_REDIS_URL` | Optional Redis for cross-replica session affinity |
| `MODEL_ROUTER_FEEDBACK_PATH` | Optional path for `/v1/router/feedback` JSONL |

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
