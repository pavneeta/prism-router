# Security Policy

## Supported versions

Security fixes are applied on the latest `main` and current `v*` release tags.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email the maintainer via the address on the [GitHub profile](https://github.com/pavneeta) for `pavneeta/prism-router`, or open a **private** GitHub security advisory on the repository (Security → Advisories → New draft advisory) if enabled.

Include:

- Affected version / commit
- Reproduction steps
- Impact (e.g. unauthenticated spend against provider keys, secret leakage)

## Operator checklist before a public deploy

1. Set **`MODEL_ROUTER_API_KEYS`** (comma-separated client keys). Without this, anyone who can reach the gateway can spend your Fireworks / OpenAI / Anthropic keys.
2. Prefer **`MODEL_ROUTER_RATE_LIMIT_RPM`** plus Railway/edge limits.
3. Keep provider keys only in Railway/host secrets — never in the repo.
4. Leave `MODEL_ROUTER_DRY_RUN=false` and `MODEL_ROUTER_MIRROR_MODE=false` unless intentionally testing.
5. Rotate any keys that were ever pasted into chat, tickets, or commits ([docs/SECURITY.md](docs/SECURITY.md)).

Debug routes under `/v1/router/*` (explain, sessions, usage metrics) are gated by the same client API keys when configured.
