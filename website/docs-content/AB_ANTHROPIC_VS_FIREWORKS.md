# A/B: Anthropic vs Fireworks (session snapshot)

Live gateway A/B from this project session (cache-busted). Re-run:

```bash
# optional dedicated harness if present:
# python scripts/ab_anthropic_vs_fireworks.py --mode gateway --with-auto --bust-cache
```

## Headline findings

| Dimension | Winner | Detail |
| --- | --- | --- |
| Cost | **Fireworks** | ~2.9× cheaper than Claude Sonnet on the sample suite |
| Latency consistency | **Anthropic Sonnet** | Lower mean / less variance than Kimi on FW |
| Coding quality | Tie | Both usable; router `auto` preferred DeepSeek |
| Chat UX | **Anthropic** | Less CoT dump at low max_tokens |
| Router `auto` | Not Anthropic | DeepSeek / gpt-4o-mini when floors allow |

Implication for Prism Router: keep Fireworks OSS models enabled for cost; use Anthropic when floors require higher intelligence or chat quality. Fireworks CoT dumps are suppressed by default via `fireworks_hide_thinking` (`reasoning_effort=none` / `thinking.type=disabled`) — see [USAGE.md](USAGE.md).
