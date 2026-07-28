# Troubleshooting

| Symptom | Fix |
| --- | --- |
| Port 4000 in use | `lsof -ti :4000 \| xargs kill` |
| `502` from chat | Check provider keys in `.env`, enabled rows in `models.yaml`, gateway logs |
| Always expensive model | Lower floors in `policy.yaml`; enable cheaper models; use `/v1/router/explain` |
| Affinity not sticking | Send stable `X-Session-Id`; affinity is in-memory per process |
| Anthropic `temperature=0` error | Update code (`litellm.drop_params=True`) |
| OpenCode cannot connect | Gateway up? Run from project with `opencode.json`; `baseURL` ends with `/v1` |
| Hermes cannot connect | `provider: custom`, `base_url: http://127.0.0.1:4000/v1`, `default: auto` |

Secrets: see [SECURITY.md](SECURITY.md). Full harness docs: [OPENCODE.md](OPENCODE.md), [HERMES.md](HERMES.md).
