# CI / automation

## Pytest (every PR / push to `main`)

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)

Runs `pip install -e ".[dev]"`, `pytest -q`, and `scripts/cpt_routing_eval.py`.

## Monthly benchmark refresh

Workflow: [`.github/workflows/update-benchmarks.yml`](../.github/workflows/update-benchmarks.yml)

| Trigger | When |
| --- | --- |
| Schedule | `0 6 1 * *` — **06:00 UTC on the 1st of each month** |
| Manual | Actions → **Update benchmarks** → **Run workflow** |

What it does:

1. Checks out the repo and installs Python 3.11 + PyYAML
2. Runs [`scripts/update_benchmarks.py`](../scripts/update_benchmarks.py) (public HTTP only — **no** Fireworks / OpenAI / Anthropic / AA API keys)
3. If `config/benchmarks.yaml` changed, opens a PR titled `chore: monthly benchmark refresh (YYYY-MM)` via `peter-evans/create-pull-request` and `GITHUB_TOKEN`

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
| DeepSWE | Live JSON from `deepswe.datacurve.ai` |
| Arena Elo | Community API (`api.wulong.dev`) + HF datasets-server mirror |
| SWE-bench Verified | Best-effort public JSON mirrors (skip if unmapped) |
| Terminal-Bench | Best-effort public JSON mirrors (skip if unmapped) |
| AA Intelligence Index | Best-effort public endpoints (often auth-gated → skip) |

Unavailable sources are skipped; partial updates and a bumped `snapshot_date` are OK. See [BENCHMARKS.md](BENCHMARKS.md).

## Docker release (GHCR)

Workflow: [`.github/workflows/release.yml`](../.github/workflows/release.yml)

On `v*` tags (or manual dispatch), builds the [`Dockerfile`](../Dockerfile) and pushes to `ghcr.io/<owner>/<repo>:$tag` and `:latest`.

## Website

- Production: [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) (Vercel project `prism-router`, Root Directory `website`)
- Docs UI: [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs) — markdown is synced via `website/sync-docs.sh` into `website/docs-content/` (also the Vercel `buildCommand`)
- Redeploy marketing: `cd website && npx vercel@latest --prod` (GitHub→Vercel auto-deploy may lag; push alone does not always refresh production)
- Optional GitHub Pages: [`.github/workflows/deploy-website.yml`](../.github/workflows/deploy-website.yml) skips unless Pages is already enabled in repo settings (Settings → Pages → GitHub Actions). Without that, the old workflow failed every `website/**` push with `Resource not accessible by integration`.
