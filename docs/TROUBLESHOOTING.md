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
| OpenCode cannot connect | Gateway up? Run from project with `opencode.json`; `baseURL` ends with `/v1` |
| Hermes cannot connect | `provider: custom`, `base_url: http://127.0.0.1:4000/v1`, `default: auto` — or `python scripts/hermes_smoke.py` |

## Fireworks: hide thinking tokens

Yes — Fireworks exposes this on [chat completions](https://docs.fireworks.ai/api-reference/post-chatcompletions):

| Knob | Effect |
| --- | --- |
| `reasoning_effort: "none"` | Disable reasoning computation / thinking phase |
| `thinking: {"type": "disabled"}` | Anthropic-compatible equivalent of `reasoning_effort: "none"` |
| `reasoning_history: "disabled"` | Strip historical `reasoning_content` from multi-turn prompts |

Some models put CoT in a separate `reasoning_content` field; others leak into `content` unless thinking is disabled (notably some Kimi / Qwen reasoning deployments). Prism Router enables the first two by default for `fireworks_ai/*` models via `policy.fireworks_hide_thinking`.

Secrets: [SECURITY.md](SECURITY.md). Harness docs: [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md).
