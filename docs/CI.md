# CI / automation

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
| DeepSWE | Live JSON from `deepswe.datacurve.ai/artifacts/.../leaderboard-live.json` |
| SWE-bench Verified | Stub (no stable public JSON mapped) |
| Terminal-Bench v2.1 | Stub (tbench / AA HTML only today) |
| AA Intelligence Index | Stub (AA API requires a key — not used in CI) |
| Arena Elo | Stub (no stable unauthenticated JSON) |

Unavailable sources are skipped; partial updates and a bumped `snapshot_date` are OK. See [BENCHMARKS.md](BENCHMARKS.md).
