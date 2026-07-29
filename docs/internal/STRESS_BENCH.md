# Stress bench (50 scenarios · multi-provider)

Calibrate Prism floors and OSS eligibility with a first-party scenario pack.

## Dataset

- Pack: [`benchmarks/scenarios/v1/scenarios.jsonl`](../../benchmarks/scenarios/v1/scenarios.jsonl)
- Manifest: [`benchmarks/scenarios/v1/manifest.yaml`](../../benchmarks/scenarios/v1/manifest.yaml)
- Regenerate: `python scripts/generate_stress_scenarios.py`

50 scenarios across all 8 task types (`code_generation` … `general_chat`).

## Run

```bash
# terminal 1
MODEL_ROUTER_DRY_RUN=true model-router   # or live with keys in .env

# terminal 2 — dry wiring check
python scripts/stress_bench.py --dry-run

# live burn (~2–3M tokens target)
MODEL_ROUTER_DRY_RUN=false model-router
# ensure OPENAI_API_KEY / ANTHROPIC_API_KEY / FIREWORKS_API_KEY on the gateway
python scripts/stress_bench.py --live --token-budget 2800000
```

Outputs under `logs/stress_bench/<run_id>/`: `results.jsonl`, `metrics.json`, `report.md`.

Live aggregates (no secrets) can be copied to `docs/internal/stress_runs/`.

## Models

Default panel: `auto`, `gpt-4o-mini`, `gpt-5.6-luna`, `claude-sonnet-5`, `deepseek-v4-pro`, `kimi-k3`, `glm-5.2`.

## Product feedback

The report includes:

- Pass rate by task × model
- Classifier accuracy vs `expect_task`
- Hints to raise/lower `min_accuracy_by_task` when OSS clearly over/under-performs
