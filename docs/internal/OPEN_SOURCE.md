# Open-source readiness checklist

Use this before flipping [pavneeta/prism-router](https://github.com/pavneeta/prism-router) to **public**.

**Private ops fork (Railway production hostname + runbooks):**  
https://github.com/pavneeta/prism-router-private — see `docs/private/RAILWAY_PRODUCTION.md` there only.

**Target:** public by **Sunday 2026-10-04** (weekend of Oct 1–4, 2026).

---

## Weekend execution order

### Thu–Fri (prep)

- [x] Open-source prep branch: client auth, OSS docs, URL scrub ([PR #6](https://github.com/pavneeta/prism-router/pull/6))
- [x] Public tree: `up.railway.app` only as `<your-service>` placeholders (`rg 'up.railway.app' README.md docs/ website/`)
- [ ] Merge **PR #6** into `main`; leave **PR #5** (usage metrics) for post-launch unless you want it in v0.2
- [ ] `pytest -q` on `main` after merge
- [ ] Redeploy Vercel site from `main` (`cd website && npx vercel@latest --prod` if GitHub hook lags)

### Sat (secrets & smoke)

- [ ] Set **`MODEL_ROUTER_API_KEYS`** (+ optional `MODEL_ROUTER_RATE_LIMIT_RPM`) on any internet-facing Railway gateway
- [ ] Smoke: unauthenticated `POST /v1/chat/completions` → **401**; with Bearer client key → **200** (or dry-run routing)
- [ ] **Rotate provider keys** if any were pasted into Cursor chat ([SECURITY.md](../SECURITY.md))
- [ ] Confirm **`.env` is not tracked** (`git ls-files .env` empty)

### Sun (go public)

- [ ] Final scan: no private hostnames in working tree (`rg -i 'railway\.app' --glob '!docs/internal/stress_runs/**'`)
- [ ] Optional: history scrub for old production URLs in git (see below) — **only with explicit approval**; not required if tree is clean
- [ ] `gh repo edit pavneeta/prism-router --visibility public`
- [ ] Verify README + [prism-router-ten.vercel.app](https://prism-router-ten.vercel.app) look correct
- [ ] Optional: make GHCR package public (Settings → Packages → `prism-router` → Change visibility)
- [ ] Announce / watch Issues for first contributors

---

## Must-do (blocking)

- [ ] Confirm **no** private production hostnames appear in the public tree (`rg 'up.railway.app' README.md docs/ website/` should only show placeholders like `<your-service>`).
- [ ] Set **`MODEL_ROUTER_API_KEYS`** on any internet-facing gateway you still run privately.
- [ ] **Rotate provider keys** if any were pasted into Cursor chat ([docs/SECURITY.md](../SECURITY.md)).
- [ ] Confirm **`.env` is not tracked** (`git ls-files .env` empty).
- [ ] Merge open-source prep PR; keep production URLs only on the private ops fork.

## Should ship if time (OSS-friendly, not blocking)

- [ ] [PR #5](https://github.com/pavneeta/prism-router/pull/5) — token usage metrics endpoint
- [ ] Shared **Redis** (or equivalent) for cross-replica session affinity ([RAILWAY.md](../RAILWAY.md) follow-ups)
- [x] GitHub Issue templates
- [x] `CURSOR.md` for Cursor / agent harness users
- [ ] First “good first issue” labels (post-public)

## Post-launch (defer)

- Anonymized per-interaction benchmark loop ([ARCHITECTURE.md](ARCHITECTURE.md))
- LiteLLM `CustomRoutingStrategy` / routing-plugin mode
- Anthropic Messages parity beyond current LiteLLM path
- Edge/CDN hard rate limits in front of public gateway
- Full git history rewrite to remove leaked URLs (optional hygiene)

## Optional: git history scrub

Past commits may still mention an old `*.up.railway.app` hostname. The **current tree** is scrubbed; rewriting history requires `git filter-repo` or BFG and **force-push** to `main` — coordinate before go-public if you care about searchability in GitHub UI.

## Repo hygiene

- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, root `SECURITY.md`
- [x] Optional client auth (`MODEL_ROUTER_API_KEYS`)
- [x] Public docs are local / self-host first (no hosted Railway demo URL)
- [x] Private fork holds Railway production bits
- [x] Site footer license matches Apache-2.0

## After going public

```bash
gh repo edit pavneeta/prism-router --visibility public
```
