# Use with HolmesGPT

Point [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) — the CNCF SRE agent — at **your** Prism Router `/v1` via Holmes’ **OpenAI-compatible** provider path ([docs](https://holmesgpt.dev/latest/ai-providers/openai-compatible/)).

```text
HolmesGPT  --LiteLLM openai/*-->  Prism Router (/v1)  --LiteLLM-->  Providers
                                  model: openai/auto  (or auto)
                                  tools / function calling required
```

Self-host the gateway first. Holmes only needs a placeholder `OPENAI_API_KEY` and `OPENAI_API_BASE` pointing at **your** Prism `/v1` (`https://<your-prism-host>/v1`). Provider API keys stay on the **gateway** (`.env`). `http://127.0.0.1:4000/v1` is only the local example after `model-router` is running.

> **Requirement:** HolmesGPT needs **function calling**. Enable tool-capable deployments in [`config/models.yaml`](../config/models.yaml) (OpenAI / Anthropic / Fireworks models that support tools).

## Quick start (CLI)

```bash
# Point Holmes at YOUR gateway
export OPENAI_API_BASE="https://<your-prism-host>/v1"
export OPENAI_API_KEY="none"   # required by LiteLLM; gateway ignores it
holmes ask "what pods are failing?" --model="openai/auto"
```

**Local example** (after `model-router` is running):

```bash
# terminal 1 — Prism
model-router

# terminal 2 — Holmes
export OPENAI_API_BASE="http://127.0.0.1:4000/v1"
export OPENAI_API_KEY="none"
holmes ask "what pods are failing?" --model="openai/auto"
```

`openai/auto` tells Holmes’ LiteLLM client to use the OpenAI-compatible transport; Prism treats any `*/auto` id as **route for me**.

Optional session affinity (if your Holmes build forwards custom headers via LiteLLM `extra_headers`):

```bash
export OPENAI_API_BASE="https://<your-prism-host>/v1"
# Local example: export OPENAI_API_BASE="http://127.0.0.1:4000/v1"
# Prefer a stable id per investigation / ticket
```

Example configs in this repo: [`examples/holmesgpt/`](../examples/holmesgpt/).

## Holmes Helm values

```yaml
# examples/holmesgpt/helm-values.yaml
additionalEnvVars:
  - name: OPENAI_API_BASE
    value: "http://prism-router.default.svc.cluster.local:4000/v1"
  - name: OPENAI_API_KEY
    value: "none"

modelList:
  prism-auto:
    api_key: "{{ env.OPENAI_API_KEY }}"
    api_base: "{{ env.OPENAI_API_BASE }}"
    model: openai/auto
    temperature: 1

config:
  model: "prism-auto"
```

For Robusta’s nested chart, nest the same keys under `holmes:`.

## Config file (`modelList`)

```yaml
# examples/holmesgpt/config.snippet.yaml
modelList:
  prism-auto:
    api_key: "{{ env.OPENAI_API_KEY }}"
    api_base: "{{ env.OPENAI_API_BASE }}"
    model: openai/auto
    temperature: 1

config:
  model: prism-auto
```

## Smoke

```bash
# gateway up (local example: :4000)
python scripts/holmesgpt_smoke.py
```

The smoke sends a Holmes-shaped chat completion **with tools** (function-calling path) using model `openai/auto`.

## Verify routing

```bash
export OPENAI_API_BASE="https://<your-prism-host>/v1"
# Local example: export OPENAI_API_BASE="http://127.0.0.1:4000/v1"

curl -s "$OPENAI_API_BASE/router/explain" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "openai/auto",
    "messages": [{"role":"user","content":"Diagnose CrashLoopBackOff on payments"}],
    "tools": [{"type":"function","function":{"name":"kubectl_logs","parameters":{"type":"object"}}}]
  }' | python -m json.tool
```

Expect a `tool_use_agent` (or related) classification and an eligible tool-capable model.

## Notes

| Topic | Detail |
| --- | --- |
| Model id | Prefer `openai/auto` from Holmes; Prism also accepts `auto` / `model-router/auto` |
| Auth | Real provider keys on Prism only; Holmes `OPENAI_API_KEY=none` is fine |
| Tools | Must be supported end-to-end; Prism forwards `tools` / `tool_choice` to LiteLLM |
| Streaming | Supported on `/v1/chat/completions` (`stream: true` → OpenAI SSE). Prefer that path if Holmes streams. |
| Docs upstream | [OpenAI-Compatible](https://holmesgpt.dev/latest/ai-providers/openai-compatible/) |

Troubleshooting: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
