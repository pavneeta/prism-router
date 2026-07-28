# External benchmark sources (initial seed)

Snapshot date: **2026-07-25** (DeepSWE) / **2026-07** (AA, Terminal-Bench, Arena).  
These seed scores drive Model-Router’s intelligence floors. Replace with live scrapes / eval runs as the product matures.

## Sources

| Source | What it measures | Maps to task types | Primary URL |
| --- | --- | --- | --- |
| **DeepSWE** (Datacurve) | Long-horizon SE agents, 113 original tasks, mini-swe-agent pass@1 | `code_generation`, `code_review_debug` | https://deepswe.datacurve.ai/ |
| **SWE-bench Verified** | Real GitHub issue resolution (% resolved) | `code_review_debug`, `code_generation` | https://www.swebench.com/verified |
| **Terminal-Bench v2.1** | Agentic terminal tasks (89), pass@1 | `tool_use_agent` | https://www.tbench.ai / Artificial Analysis |
| **Artificial Analysis Intelligence Index** v4.1 | Composite intelligence (incl. Terminal-Bench, SciCode, GPQA, …) | `reasoning_math`, general intelligence prior | https://artificialanalysis.ai |
| **Arena AI** (LMArena / Chatbot Arena) | Human preference Elo (text + coding arenas) | `general_chat`, `creative_writing`, soft prior for chatty tasks | https://arena.ai |

## Normalization

| Raw metric | → Router scale `[0, 1]` |
| --- | --- |
| DeepSWE / SWE-bench / Terminal-Bench pass rates | used as-is (`0.74` = 74%) |
| AA Intelligence Index (typical top ≈ 61) | `index / 70` |
| Arena Elo (typical top text ≈ 1500–1525) | `clamp((elo - 1000) / 550, 0, 1)` |

## Task accuracy derivation

Computed in [`src/model_router/benchmarks.py`](../src/model_router/benchmarks.py):

| Task type | Formula |
| --- | --- |
| `code_generation` | mean of available(`deepswe`, `swe_bench_verified`) |
| `code_review_debug` | `swe_bench_verified` else `deepswe` |
| `tool_use_agent` | `terminal_bench_v2_1` |
| `reasoning_math` | AA normalized |
| `summarization` / `extraction_qa` | `0.6 * AA_norm + 0.4 * Arena_norm` (AA-only if no Elo) |
| `creative_writing` / `general_chat` | Arena_norm, else AA_norm |

Missing sources are skipped (no silent zeros). Models with no score for a task are ineligible for that task.

## Harness caveat

SWE-bench and DeepSWE scores depend on agent harness + effort. Prefer **mini-swe-agent** / published DeepSWE rows for fair LM comparison. Third-party SWE tables can disagree sharply (e.g. Llama 4 Maverick) — we prefer official DeepSWE + AA + Terminal-Bench when present, and mark SWE rows with `note` when harness is unclear.

## Cost fields

`input_cost_per_m` / `output_cost_per_m` / `cached_input_cost_per_m` are indicative public list prices (USD per 1M tokens) for ranking — confirm with the provider before production billing.

## Refresh

Re-pull leaderboards when:

1. A frontier model ships
2. DeepSWE / Terminal-Bench publish a new snapshot
3. AA Intelligence Index version bumps

### Automated monthly update

GitHub Actions runs [`scripts/update_benchmarks.py`](../scripts/update_benchmarks.py) on a monthly cron (`0 6 1 * *` UTC) and on `workflow_dispatch`. Best-effort public scrapes (DeepSWE live JSON today; other sources stubbed until stable public endpoints exist) update matching rows in [`config/benchmarks.yaml`](../config/benchmarks.yaml) and open a PR. No provider API secrets are required. Details: [CI.md](CI.md).

```bash
python scripts/update_benchmarks.py --dry-run -v
```
