# Contributing to Prism Router

Thanks for helping. This repo is an **intelligence- and cache-aware** OpenAI-compatible model router (FastAPI + LiteLLM).

## Development setup

```bash
git clone https://github.com/pavneeta/prism-router.git
cd prism-router
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Optional: add provider keys for live calls. Leave MODEL_ROUTER_DRY_RUN=true for routing-only.
pytest -q
python scripts/cpt_routing_eval.py
```

Gateway: `model-router` → `http://127.0.0.1:4000`.

## Project layout

| Path | Purpose |
| --- | --- |
| `src/model_router/` | Gateway, policy, classifier, cache, telemetry |
| `config/` | `models.yaml`, `benchmarks.yaml`, `policy.yaml` |
| `docs/` | User docs (synced to the marketing `/docs` UI) |
| `docs/internal/` | Engineering notes (not synced to the public site) |
| `website/` | Marketing site (Vercel root directory) |
| `tests/` | Pytest |
| `scripts/` | Stress/CPT/benchmark utilities |

## Pull requests

1. Branch from `main`.
2. Keep diffs focused; update docs when behavior changes.
3. Run `pytest -q` (and CPT eval if you touch routing/policy).
4. Do **not** commit `.env`, keys, tokens, or live stress `results.jsonl`.
5. User-facing doc edits under `docs/` — run `website/sync-docs.sh` (or rely on the Vercel `buildCommand`) so `website/docs-content/` stays aligned.

CI on every PR: install, pytest, CPT offline eval (`.github/workflows/ci.yml`).

## Releases

Maintainers: use the project **cicd-rollout** skill / tag `v*` to publish GHCR (`ghcr.io/pavneeta/prism-router`), redeploy Railway, and refresh Vercel. See `docs/internal/CI.md`.

## Security

Never paste provider keys into issues or PRs. See [SECURITY.md](SECURITY.md). Report vulnerabilities privately as described there.

## Code of conduct

Be respectful. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
