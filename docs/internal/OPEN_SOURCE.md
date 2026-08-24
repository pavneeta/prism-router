# Open-source readiness checklist

Use this before flipping [pavneeta/prism-router](https://github.com/pavneeta/prism-router) to **public**.

## Must-do (blocking)

- [ ] **Protect the hosted API:** set Railway `MODEL_ROUTER_API_KEYS` (and preferably `MODEL_ROUTER_RATE_LIMIT_RPM`) on production, redeploy, and verify unauthenticated `/v1/chat/completions` returns **401**.
- [ ] **Rotate provider keys** if any were pasted into Cursor chat, tickets, or screenshots ([docs/SECURITY.md](docs/SECURITY.md)).
- [ ] Confirm **`.env` is not tracked** (`git ls-files .env` empty) and never force-add it.
- [ ] Merge or close leftover private WIP branches / PRs you do not want public (`feat/usage-metrics`, experiment branches, stashes with local paths).
- [ ] Decide whether the **public Railway demo** stays online. If yes: client auth + rate limits. If no: remove or soft-gate the hosted URL from README/site, or take the service private.

## Repo hygiene (done in `chore/open-source-prep` when landed)

- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, root `SECURITY.md`
- [x] Optional client auth (`MODEL_ROUTER_API_KEYS`)
- [x] Product requirements moved under `docs/internal/`
- [x] `.gitignore` hardened for local stress artifacts / caches
- [x] `pyproject.toml` license + project URLs

## Nice-to-have

- [ ] Enable GitHub **private vulnerability reporting** / security advisories
- [ ] Add topics on the GitHub repo (`llm`, `routing`, `litellm`, `openai-compatible`)
- [ ] Pin a short homepage URL (marketing site) and description on GitHub
- [ ] Publish GHCR image visibility for public pulls if desired (package settings)
- [ ] Scrub or keep `docs/internal/stress_runs/` — summaries are OK; never commit raw `results.jsonl` with prompts you care about keeping private

## After going public

```bash
gh repo edit pavneeta/prism-router --visibility public
# Confirm:
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://prism-router-production.up.railway.app/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"auto","messages":[{"role":"user","content":"ping"}]}'
# Expect 401 once MODEL_ROUTER_API_KEYS is set
```
