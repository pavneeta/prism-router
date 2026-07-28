"""Unit tests for benchmark scraper payload parsers (no network)."""

from scripts.update_benchmarks import (
    _parse_aa_payload,
    _parse_arena_payload,
    _parse_swe_payload,
    _parse_terminal_payload,
)


def test_parse_arena_wulong_shape():
    payload = {
        "models": [
            {"rank": 1, "model": "Claude Opus 5", "score": 1400},
            {"rank": 2, "model": "gpt-4o-mini", "score": 1200},
        ]
    }
    scores = _parse_arena_payload(payload)
    assert scores["anthropic/claude-opus-5"] == 1400
    assert scores["openai/gpt-4o-mini"] == 1200


def test_parse_arena_hf_rows():
    payload = {
        "rows": [
            {
                "row": {
                    "model_name": "claude-sonnet-5",
                    "rating": 1301.5,
                    "category": "overall",
                }
            }
        ]
    }
    scores = _parse_arena_payload(payload)
    assert scores["anthropic/claude-sonnet-5"] == 1301.5


def test_parse_swe_percent():
    payload = {"results": [{"model": "gpt-4o agent", "resolved": 45.0}]}
    scores = _parse_swe_payload(payload)
    assert scores["openai/gpt-4o"] == 0.45


def test_parse_terminal():
    payload = [{"name": "kimi-k3 agent", "pass_at_1": 0.33}]
    scores = _parse_terminal_payload(payload)
    assert scores["moonshot/kimi-k3"] == 0.33


def test_parse_aa():
    payload = {"models": [{"name": "DeepSeek V4 Pro", "intelligence_index": 62}]}
    scores = _parse_aa_payload(payload)
    assert scores["deepseek/deepseek-v4-pro"] == 62.0
