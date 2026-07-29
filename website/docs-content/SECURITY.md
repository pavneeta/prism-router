# Secret handling

## Never commit

- `.env` (gitignored)
- Provider API keys in docs, issues, or chat

## Keys used with this project

| Provider | Env var | Rotate at |
| --- | --- | --- |
| Fireworks | `FIREWORKS_API_KEY` | https://app.fireworks.ai |
| OpenAI | `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| Anthropic | `ANTHROPIC_API_KEY` | https://console.anthropic.com |

If a key was pasted into chat, email, or a ticket: **revoke it and create a new one**, then update local `.env` only.

## Checklist after rotation

1. Revoke old keys in each provider console
2. Put new values in `.env` (never commit)
3. Restart the gateway: `model-router`
4. Smoke: `curl http://127.0.0.1:4000/health` and a short `/v1/chat/completions` call

## CI secrets

- Monthly benchmark job needs **no** provider keys
- Optional Vercel deploy needs `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` as GitHub Actions secrets
- GHCR release uses built-in `GITHUB_TOKEN`
