# CI / automation

## Pytest (every PR / push to `main`)

Workflow: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

Runs `pip install -e ".[dev]"`, `pytest -q`, and `scripts/cpt_routing_eval.py`.

## Monthly benchmark refresh

Workflow: [`.github/workflows/update-benchmarks.yml`](../../.github/workflows/update-benchmarks.yml)

| Trigger | When |
| --- | --- |
| Schedule | `0 6 1 * *` — **06:00 UTC on the 1st of each month** |
| Manual | Actions → **Update benchmarks** → **Run workflow** |

What it does:

1. Checks out the repo and installs Python 3.11 + PyYAML
2. Runs parser unit tests, then [`scripts/update_benchmarks.py`](../../scripts/update_benchmarks.py) (public HTTP only — **no** Fireworks / OpenAI / Anthropic / AA API keys)
3. Refreshes exact scores **and** discovers latest public model IDs (Together docs, DeepSWE/Arena slugs, optional Fireworks docs)
4. Always bumps `snapshot_date`, writes `last_refresh` with a skip summary, and opens a PR titled `chore: monthly benchmark and model refresh (YYYY-MM)` via `peter-evans/create-pull-request` and `GITHUB_TOKEN` — even when every source failed
5. New curated aliases without public scores are added to `config/models.yaml` + `config/benchmarks.yaml` as `auto_select: false` passthrough (`pending public scores`). DeepSWE/SWE numbers are never invented.

Merge that PR so the next deploy picks up updated floors/scores for `auto`. `GET /ready` reports `benchmarks_snapshot_date`.

**Repo setting required:** Settings → Actions → General → **Allow GitHub Actions to create and approve pull requests**. Without that, the scrape still runs and pushes a branch, but PR creation fails (open the PR manually from the branch).

### Run locally

```bash
# Report only (no write)
python scripts/update_benchmarks.py --dry-run -v

# Write updates + markdown summary (logs/ is gitignored)
python scripts/update_benchmarks.py --summary logs/benchmark_update_summary.md -v
```

### Scraper coverage

| Source | Status |
| --- | --- |
| DeepSWE | Live JSON from `deepswe.datacurve.ai` + leaderboard ID discovery |
| Arena Elo | Official HF datasets-server (`lmarena-ai/leaderboard-dataset`) + ID discovery |
| SWE-bench Verified | Official mini-SWE-agent rows (skip if unmapped) |
| Terminal-Bench | Official TB 2.0 leaderboard (skip if unmapped) |
| Together public models | Serverless docs table (no API key) — used to discover latest IDs |
| Fireworks public models | Optional public docs IDs (skip if the page is unavailable) |
| AA Intelligence Index | Documented Data API requires `x-api-key` — skipped; no key used |

Unavailable sources are skipped; the job still writes `last_refresh`, bumps `snapshot_date`, and opens a PR. See [BENCHMARKS.md](../BENCHMARKS.md).

## Docker release (GHCR)

Workflow: [`.github/workflows/release.yml`](../../.github/workflows/release.yml)

On `v*` tags (or manual dispatch), builds the [`Dockerfile`](../../Dockerfile) and pushes to `ghcr.io/<owner>/<repo>:$tag` and `:latest`.

## Website

- Production: [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) (Vercel project `prism-router`, Root Directory `website`)
- Docs UI: [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs) — markdown is synced via `website/sync-docs.sh` into `website/docs-content/` (also the Vercel `buildCommand`)
- Redeploy marketing: `cd website && npx vercel@latest --prod` (GitHub→Vercel auto-deploy may lag; push alone does not always refresh production)
- Optional GitHub Pages: [`.github/workflows/deploy-website.yml`](../../.github/workflows/deploy-website.yml) skips unless Pages is already enabled in repo settings (Settings → Pages → GitHub Actions). Without that, the old workflow failed every `website/**` push with `Resource not accessible by integration`.
- API gateway on Railway: [RAILWAY.md](../RAILWAY.md) (`Dockerfile` + `railway.toml`)
