# Prism Router roadmap

Engineering tracker (not synced to the public docs site).

| Status | Item | Notes / issue |
| --- | --- | --- |
| Done | Candidate A intelligence floors (`config/policy.yaml`) | Stress PASS — tool_use −73%, cg+tu −31% |
| Done | Token usage metrics (`GET /v1/router/metrics/usage`) | Merged via routing backlog PR |
| Done | Redis-backed session affinity (`MODEL_ROUTER_REDIS_URL`) | Falls back to in-memory |
| Done | Latency bias in selection (`latency_penalty_usd_per_ms`) | Default `0` (off) |
| Done | Provider health EWMA deprioritization | In-process; `/ready` snapshot |
| Done | Observed sticky ratio → affinity margin | Session rollups |
| Done | Outcome feedback API (`POST /v1/router/feedback`) | JSONL only |
| Done | OpenAI-compatible streaming | PR #4 |
| Done | Client auth + OSS prep | PR #6 |
| In progress | Multi-replica session **task** memory | Still in-memory per replica |
| In progress | Cluster-wide usage metrics | Per-replica today |
| Deferred | Multi-tenant billing/auth beyond `MODEL_ROUTER_API_KEYS` | [#8](https://github.com/pavneeta/prism-router/issues/8) |
| Deferred | LiteLLM CustomRoutingStrategy plugin | [#9](https://github.com/pavneeta/prism-router/issues/9) |
| Deferred | Semantic / fuzzy local prompt cache | [#10](https://github.com/pavneeta/prism-router/issues/10) |
| Deferred | Learned tiny classifier | [#11](https://github.com/pavneeta/prism-router/issues/11) |
| Deferred | Bandits / IPS / full adaptive routing | [#12](https://github.com/pavneeta/prism-router/issues/12) |
| Deferred | Git history scrub | [#13](https://github.com/pavneeta/prism-router/issues/13) |
| Deferred | Edge CDN rate limits | [#14](https://github.com/pavneeta/prism-router/issues/14) |
| Wontfix (MVP) | Anthropic `/v1/messages` streaming | Use `/v1/chat/completions?stream=true` |

Issue numbers in the Deferred row are placeholders until issues are created; update links after `gh issue create`.
