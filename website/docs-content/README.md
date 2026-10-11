# Documentation index

Prism is a **self-hosted** OpenAI-compatible gateway. After you run it, point clients at **your** `/v1` — `https://<your-prism-host>/v1` or `$OPENAI_API_BASE`. `http://127.0.0.1:4000/v1` is only the local example after `model-router` is running.

User / operator guides (also rendered on the marketing site `/docs`):

| Doc | Contents |
| --- | --- |
| [USAGE.md](USAGE.md) | Local install, API, sessions, streaming |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common errors + Fireworks CoT hide settings |
| [SECURITY.md](SECURITY.md) | Key rotation |
| [TOGETHER.md](TOGETHER.md) | Together.ai setup and default open-weight mappings |
| [OPENCODE.md](OPENCODE.md) | OpenCode harness |
| [HERMES.md](HERMES.md) | Hermes Agent harness |
| [HOLMESGPT.md](HOLMESGPT.md) | HolmesGPT (CNCF SRE agent) harness |
| [BENCHMARKS.md](BENCHMARKS.md) | Score provenance |
| [RAILWAY.md](RAILWAY.md) | Deploy API gateway on Railway |

<details>
<summary>Internal (GitHub only)</summary>

Engineering docs live under [`docs/internal/`](internal/) and are **not** synced to the public docs UI:

| Doc | Contents |
| --- | --- |
| [ARCHITECTURE.md](internal/ARCHITECTURE.md) | System design |
| [CI.md](internal/CI.md) | Pytest, monthly scrapers, GHCR, Vercel |
| [HARNESS_BENCH.md](internal/HARNESS_BENCH.md) | Cross-harness × provider bench |
| [STRESS_BENCH.md](internal/STRESS_BENCH.md) | 50-scenario multi-provider stress bench |
| [AB_ANTHROPIC_VS_FIREWORKS.md](internal/AB_ANTHROPIC_VS_FIREWORKS.md) | A/B session notes |
| [OPEN_SOURCE.md](internal/OPEN_SOURCE.md) | Checklist before making the GitHub repo public |
| [REQUIREMENTS.md](internal/REQUIREMENTS.md) | Original product requirements notes |
| [stress_runs/](internal/stress_runs/) | Stress bench aggregates |

</details>

**Site:** [https://prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) · **Docs UI:** [https://prism-router-ten.vercel.app/docs](https://prism-router-ten.vercel.app/docs) · **Repo:** [pavneeta/prism-router](https://github.com/pavneeta/prism-router)

The marketing site docs page (`/docs`) renders **user docs only**. Content is synced into `website/docs-content/` at deploy time (`website/sync-docs.sh`). Contributors: put eng-facing writeups in `docs/internal/`.
