# External benchmark sources

Catalog refresh: **2026-10-11**. Source snapshots differ and are recorded below and in
[`config/benchmarks.yaml`](../config/benchmarks.yaml). Scores are added only for exact,
documented model/config aliases; ambiguous family aliases are skipped. Together catalog
rows from `main` are preserved; only `together/deepseek-v4-pro` is mapped to the same
public DeepSeek-V4 Pro rows as the provider-neutral id.

## Sources

| Source | What it measures | Maps to task types | Primary URL |
| --- | --- | --- | --- |
| **DeepSWE v1.1** | Long-horizon SE, 113 original tasks, mini-swe-agent pass@1 | `code_generation`, fallback for `code_review_debug` | [live JSON](https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json) — generated 2026-09-22 |
| **SWE-bench Verified** | Real GitHub issue resolution; mini-SWE-agent rows only | `code_review_debug` | [official leaderboard payload](https://www.swebench.com/index.html) — fetched 2026-10-11 |
| **SWE-rebench** | Fresh multilingual real-world issues, Resolved Rate | catalog comparison only | [leaderboard](https://swe-rebench.com/) — latest public window |
| **Terminal-Bench v2.1 (historical)** | AA-sourced agentic terminal pass@1 used for routing | `tool_use_agent` | Retained from 2026-07; official TB 2.0 uses a different scale |
| **Terminal-Bench 2.0** | Official model+agent accuracy | diagnostic only | [official leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.0) — fetched 2026-10-11, rows through 2026-09-29 |
| **Artificial Analysis Intelligence Index** | Composite intelligence | `reasoning_math`, general prior | [Data API docs](https://artificialanalysis.ai/data-api/docs) — current v4.3.2 requires `x-api-key`; not refreshed |
| **LMArena** | Human preference Bradley-Terry rating, overall and coding | overall drives chat priors; coding retained for comparison | [official HF dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) — published 2026-10-08 |

## Normalization

| Raw metric | → Router scale `[0, 1]` |
| --- | --- |
| DeepSWE / SWE-bench / SWE-rebench / Terminal-Bench rates | used as-is (`0.74` = 74%) |
| AA Intelligence Index (typical top ≈ 61) | `index / 70` |
| LMArena overall rating (typical top text ≈ 1500–1525) | `clamp((rating - 1000) / 550, 0, 1)` |

`swe_rebench_resolved`, `arena_coding_elo`, and `terminal_bench_2` are retained as
directly comparable diagnostics. They do not currently alter derived routing
accuracy. Official Terminal-Bench 2.0 accuracies are on a different scale than the
historical AA v2.1 numbers still used for `tool_use_agent` (floor 0.70).

## Task accuracy derivation

Computed in [`src/model_router/benchmarks.py`](../src/model_router/benchmarks.py):

| Task type | Formula |
| --- | --- |
| `code_generation` | **DeepSWE only** (SWE-bench alone is not used — too saturated / harness-skewed) |
| `code_review_debug` | `swe_bench_verified` else `deepswe` |
| `tool_use_agent` | `terminal_bench_v2_1` (official `terminal_bench_2` is diagnostic only) |
| `reasoning_math` | AA normalized |
| `summarization` / `extraction_qa` | `0.6 * AA_norm + 0.4 * Arena_norm` (AA-only if no Elo) |
| `creative_writing` / `general_chat` | Arena_norm, else AA_norm |

Missing sources are skipped (no silent zeros). Models with no score for a task are ineligible for that task.

## First-party stress calibration

Use [`docs/internal/STRESS_BENCH.md`](internal/STRESS_BENCH.md) (`scripts/stress_bench.py`) to measure pass rates on 50 internal scenarios across OpenAI / Anthropic / OSS and feed floor reviews.

- Dry-run wiring: [`docs/internal/stress_runs/20260728T144931Z_dry_summary.md`](internal/stress_runs/20260728T144931Z_dry_summary.md)
- Live burn (router, 2026-07-28): [`docs/internal/stress_runs/20260728T172948Z_summary.md`](internal/stress_runs/20260728T172948Z_summary.md)

SWE-bench and DeepSWE scores depend on agent harness and effort. SWE-bench values here
use only exact model tags from official **mini-SWE-agent** rows. DeepSWE and
Terminal-Bench use the highest published effort for the exact catalog family and
record that choice in model notes. Multi-model agents and broad aliases such as
`deepseek`, `gpt-5`, or an older Opus release are never mapped to a newer catalog ID.

## Unavailable or intentionally skipped sources

- **Artificial Analysis**: the documented v2 Data API requires an `x-api-key`.
  The refresh uses no provider keys, so the 2026-07 AA values remain explicitly
  historical. The public chart is not treated as a stable machine-readable feed.
- **LiveCodeBench**: skipped because execution pass@1 is not directly comparable to
  the catalog's long-horizon software-agent metrics.
- **τ-bench**: skipped because domain, tool-policy, and harness variants do not map
  defensibly to the existing catalog source keys.
- Sources without an exact model/config match are omitted rather than inferred.

## Cost fields

`input_cost_per_m` / `output_cost_per_m` / `cached_input_cost_per_m` are indicative public list prices (USD per 1M tokens) for ranking — confirm with the provider before production billing.

## Refresh

Re-pull leaderboards when:

1. A frontier model ships
2. DeepSWE / Terminal-Bench publish a new snapshot
3. AA Intelligence Index version bumps

### Automated monthly update

GitHub Actions runs [`scripts/update_benchmarks.py`](../scripts/update_benchmarks.py)
monthly (`0 6 1 * *` UTC) and on `workflow_dispatch`. Each run:

1. Refreshes exact catalog matches from DeepSWE, SWE-bench, SWE-rebench,
   Terminal-Bench, and LMArena
2. Discovers latest public model IDs from Together serverless docs (no API key),
   DeepSWE/Arena leaderboard slugs, and optional Fireworks public docs
3. Maps new IDs onto curated aliases (for example `zai-org/GLM-5.3` → `zai/glm-5.3`).
   Models with public scores get those scores; models without scores are added as
   `auto_select: false` passthrough with notes `pending public scores`
4. Always bumps `snapshot_date` and writes `last_refresh` (including skipped
   sources), then opens a PR even when every source failed

DeepSWE and SWE numbers are never invented. Operators merge the PR so the next
deploy picks up updated floors/scores for `auto`. `GET /ready` exposes
`benchmarks_snapshot_date`.

No provider API secrets are read or required.

**Repo setting required:** Settings → Actions → General → **Allow GitHub Actions
to create and approve pull requests**.

```bash
python scripts/update_benchmarks.py --dry-run -v
```
