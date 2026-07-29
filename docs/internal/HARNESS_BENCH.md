# Harness × provider benchmarking

Script: [`scripts/harness_provider_bench.py`](../../scripts/harness_provider_bench.py)

Exercises **OpenCode**, **Hermes**, and **HolmesGPT** request shapes against:

| Mode | Model |
| --- | --- |
| `auto` | harness-native auto id |
| `openai` | `openai/gpt-4o-mini` |
| `anthropic` | `anthropic/claude-sonnet-5` |
| `open` | `deepseek/deepseek-v4-pro` (Fireworks) |

Prompts: chat · code · agent (tools).

```bash
# Dry-run (no provider keys) — routing + estimated $
MODEL_ROUTER_DRY_RUN=true model-router
python scripts/harness_provider_bench.py --dry-run -o logs/harness_provider_bench.md

# Live (needs OPENAI_API_KEY / ANTHROPIC_API_KEY / FIREWORKS_API_KEY in .env)
MODEL_ROUTER_DRY_RUN=false model-router
python scripts/harness_provider_bench.py --live -o logs/harness_provider_bench_live.md
```

Latest dry-run artifact (local, gitignored): `logs/harness_provider_bench.md`.
