# Together.ai

Prism Router calls [Together.ai](https://docs.together.ai/intro) through LiteLLM using `TOGETHER_API_KEY` on the **gateway** (never commit keys).

## Setup

```bash
# In gitignored .env
TOGETHER_API_KEY=your_together_api_key
```

Together.ai is the **default backend for open-weight stable catalog IDs** (`deepseek/*`, `zai/*`, `moonshot/*`, `minimax/*`). Pricing is in `config/benchmarks.yaml`.

Default mappings:

| Stable Prism ID | Together deployment |
| --- | --- |
| `deepseek/deepseek-v4-pro` | `deepseek-ai/DeepSeek-V4-Pro-0813` |
| `zai/glm-5.2` | `zai-org/GLM-5.2` |
| `zai/glm-5.3` | `zai-org/GLM-5.3` |
| `moonshot/kimi-k3` | `moonshotai/Kimi-K3` |
| `minimax/minimax-m3` | `MiniMaxAI/MiniMax-M3` |

Fireworks remains supported through explicit aliases (`fireworks/deepseek-v4-pro`, `fireworks/glm-5.2`, `fireworks/kimi-k3`, `fireworks/minimax-m3`) and the existing provider-cache code.

Only deployments with completed live validation are eligible for `auto` routing.
DeepSeek V4 Pro and MiniMax M3 are currently validated for `auto` routing.
GLM 5.2, **GLM 5.3**, and Kimi K3 remain explicit passthrough choices
(`auto_select: false`). GLM 5.3 has no public DeepSWE/SWE row yet — it is
listed so operators can call the latest Together GLM without inventing scores.
Together prompt caching is reported as unsupported until provider-side cache
behavior is verified.

## Smoke (passthrough)

```bash
model-router   # with TOGETHER_API_KEY set

export OPENAI_API_BASE="https://<your-prism-host>/v1"
# Local example: export OPENAI_API_BASE="http://127.0.0.1:4000/v1"

curl -sS "$OPENAI_API_BASE/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "deepseek/deepseek-v4-pro",
    "messages": [{"role": "user", "content": "Reply with exactly: together-ok"}]
  }'
```

LiteLLM model id: `together_ai/<Together model id>` (e.g. `together_ai/deepseek-ai/DeepSeek-V4.1-Flash`).

## Stress benchmark (Together panel)

```bash
MODEL_ROUTER_DRY_RUN=false model-router
python scripts/stress_bench.py --live --together-panel --limit 50 --token-budget 500000
```

Panel: `auto`, `together/deepseek-v4-pro`, `together/glm-5.3-flash`.

Some Together models (e.g. certain Qwen 3.x) require **third-party data sharing** in your Together org settings — if you see `third_party_data_sharing_blocked`, enable sharing in the [Together dashboard](https://api.together.ai/) or pick serverless models from `GET /v1/models`.

List models from Together:

```bash
curl -sS -H "Authorization: Bearer $TOGETHER_API_KEY" https://api.together.xyz/v1/models | python -m json.tool | head
```

Add new Together models by copying a row in `models.yaml` + `benchmarks.yaml`, then refresh scores when public leaderboard data is available.
