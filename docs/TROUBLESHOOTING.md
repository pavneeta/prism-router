# Troubleshooting

| Symptom | Fix |
| --- | --- |
| Port 4000 in use | `lsof -ti :4000 \| xargs kill` |
| `502` from chat | Check provider keys in `.env`, enabled rows in `models.yaml`, gateway logs |
| Empty / auth errors after key clear | Rotate keys at provider consoles and refill `.env` — see [SECURITY.md](SECURITY.md) |
| Always expensive model | Lower floors in `policy.yaml`; enable cheaper models; use `/v1/router/explain` |
| Affinity not sticking | Send stable `X-Session-Id`; affinity is in-memory per process |
| Session rollup 404 | Make at least one request with that `X-Session-Id` first |
| Anthropic `temperature=0` error | Gateway sets `litellm.drop_params=True` |
| Fireworks dumps `<think>` / CoT into chat | Keep `fireworks_hide_thinking: true` in `policy.yaml` (default). Sends `reasoning_effort=none` + `thinking.type=disabled` |
| OpenCode cannot connect | Gateway up? `baseURL` is **your** `/v1` (`https://<your-prism-host>/v1`, or local example `http://127.0.0.1:4000/v1` after `model-router`); keep `"streaming": true` unless you intentionally buffer |
| Hermes cannot connect | `provider: custom`, `base_url` = your `/v1`, `default: auto` — or `python scripts/hermes_smoke.py` |
| HolmesGPT cannot connect | `OPENAI_API_BASE` = your `/v1`, `OPENAI_API_KEY=none`, `--model=openai/auto`; tools required — see [HOLMESGPT.md](HOLMESGPT.md) |
| Anthropic client wants stream | `/v1/messages?stream=true` is not implemented — point the client at `/v1/chat/completions` with `"stream": true` |
| Stream hangs / empty SSE | Confirm upstream provider keys; dry-run still emits synthetic SSE; check gateway logs for `stream_error` chunks |

## Fireworks: hide thinking tokens

Yes — Fireworks exposes this on [chat completions](https://docs.fireworks.ai/api-reference/post-chatcompletions):

| Knob | Effect |
| --- | --- |
| `reasoning_effort: "none"` | Disable reasoning computation / thinking phase |
| `thinking: {"type": "disabled"}` | Anthropic-compatible equivalent of `reasoning_effort: "none"` |
| `reasoning_history: "disabled"` | Strip historical `reasoning_content` from multi-turn prompts |

Some models put CoT in a separate `reasoning_content` field; others leak into `content` unless thinking is disabled (notably some Kimi / Qwen reasoning deployments). Prism Router enables the first two by default for `fireworks_ai/*` models via `policy.fireworks_hide_thinking`.

Secrets: [SECURITY.md](SECURITY.md). Harness docs: [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md).
