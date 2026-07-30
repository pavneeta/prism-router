# Use with Hermes Agent

Point [Nous Hermes](https://hermes-agent.nousresearch.com/) at Prism Router via a **custom OpenAI-compatible** endpoint. Streaming is supported: Hermes may send `stream: true`; Prism returns OpenAI-style SSE on `/v1/chat/completions`.

## Config (`~/.hermes/config.yaml`)

```yaml
model:
  default: auto
  provider: custom
  base_url: https://prism-router-production.up.railway.app/v1
  # Local: http://127.0.0.1:4000/v1
  api_key: unused
```

Provider API keys stay on the **gateway** `.env`.

## Smoke

```bash
# terminal 1 (local only)
model-router

# terminal 2
python scripts/hermes_smoke.py
```

Or CLI wizard: `hermes model` → Custom endpoint → base URL ending in `/v1` → model `auto`.

See Hermes [AI Providers](https://hermes-agent.nousresearch.com/docs/integrations/providers) docs for `custom_providers` / fallbacks. Streaming caveats (cache bypass, no Anthropic `/v1/messages` stream): [USAGE.md](USAGE.md#streaming).
