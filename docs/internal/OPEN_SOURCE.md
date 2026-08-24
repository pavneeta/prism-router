# Open-source readiness checklist

Use this before flipping [pavneeta/prism-router](https://github.com/pavneeta/prism-router) to **public**.

**Private ops fork (Railway production hostname + runbooks):**  
https://github.com/pavneeta/prism-router-private — see `docs/private/RAILWAY_PRODUCTION.md` there only.

## Must-do (blocking)

- [ ] Confirm **no** private production hostnames appear in the public tree (`rg 'up.railway.app' README.md docs/ website/` should only show placeholders like `<your-service>`).
- [ ] Set **`MODEL_ROUTER_API_KEYS`** on any internet-facing gateway you still run privately.
- [ ] **Rotate provider keys** if any were pasted into Cursor chat ([docs/SECURITY.md](../SECURITY.md)).
- [ ] Confirm **`.env` is not tracked** (`git ls-files .env` empty).
- [ ] Merge open-source prep PR; keep production URLs only on the private ops fork.

## Repo hygiene

- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, root `SECURITY.md`
- [x] Optional client auth (`MODEL_ROUTER_API_KEYS`)
- [x] Public docs are local / self-host first (no hosted Railway demo URL)
- [x] Private fork holds Railway production bits

## After going public

```bash
gh repo edit pavneeta/prism-router --visibility public
```
