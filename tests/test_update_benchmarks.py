"""Unit tests for benchmark scraper payload parsers (no network)."""

from scripts.update_benchmarks import (
    _parse_aa_payload,
    _parse_arena_payload,
    _parse_swe_payload,
    _parse_swe_rebench_payload,
    _parse_terminal_payload,
    insert_source_value,
)


def test_parse_arena_official_rows_by_category():
    payload = {
        "rows": [
            {
                "row": {
                    "model_name": "claude-opus-5-max",
                    "rating": 1501.25,
                    "category": "overall",
                }
            },
            {
                "row": {
                    "model_name": "claude-opus-5-max",
                    "rating": 1550.75,
                    "category": "coding",
                }
            },
        ]
    }
    assert _parse_arena_payload(payload)["anthropic/claude-opus-5"] == 1501.25
    assert _parse_arena_payload(payload, "coding")["anthropic/claude-opus-5"] == 1550.75


def test_parse_arena_rejects_ambiguous_family_alias():
    payload = {
        "rows": [
            {
                "row": {
                    "model_name": "claude-opus-5.1-max",
                    "rating": 1301.5,
                    "category": "overall",
                }
            }
        ]
    }
    assert _parse_arena_payload(payload) == {}


def test_parse_swe_official_mini_agent_only():
    payload = [
        {
            "name": "Verified",
            "results": [
                {
                    "agent": "mini-SWE-agent",
                    "tags": ["Model: gpt-4o-20241120"],
                    "resolved": 21.62,
                },
                {
                    "agent": "Custom Agent",
                    "tags": ["Model: gpt-4o-20241120"],
                    "resolved": 90.0,
                },
            ],
        }
    ]
    scores = _parse_swe_payload(payload)
    assert scores["openai/gpt-4o"] == 0.216


def test_parse_terminal_current_shape_prefers_max_effort():
    payload = [
        {
            "metadata": {
                "model_display": {"label": "Opus 5"},
                "reasoning_effort": "xhigh",
            },
            "metrics": {"accuracy": 55.0},
        },
        {
            "metadata": {
                "model_display": {"label": "Opus 5"},
                "reasoning_effort": "max",
            },
            "metrics": {"accuracy": 51.82},
        },
    ]
    scores = _parse_terminal_payload(payload)
    assert scores["anthropic/claude-opus-5"] == 0.518


def test_parse_swe_rebench_current_window():
    text = (
        r'\"modelName\":\"GPT-5.6 Sol [medium]\",'
        r'\"taskRangeTimestamp\":{\"from\":1,\"to\":2},'
        r'\"rangeStats\":{\"all\":{\"1:2\":{\"resolvedRate\":62.342}}}'
    )
    scores, snapshot = _parse_swe_rebench_payload(text)
    assert scores["openai/gpt-5.6-sol"] == 0.623
    assert snapshot == "1970-01-01"


def test_parse_swe_rebench_prefers_latest_window():
    text = (
        r'\"modelName\":\"DeepSeek-V4 Pro [high]\",'
        r'\"taskRangeTimestamp\":{\"from\":1,\"to\":1000},'
        r'\"rangeStats\":{\"all\":{\"1:1000\":{\"resolvedRate\":40.2}}}'
        r'\"modelName\":\"DeepSeek-V4 Pro [high]\",'
        r'\"taskRangeTimestamp\":{\"from\":1,\"to\":2000},'
        r'\"rangeStats\":{\"all\":{\"1:2000\":{\"resolvedRate\":41.4}}}'
    )
    scores, _snapshot = _parse_swe_rebench_payload(text)
    assert scores["deepseek/deepseek-v4-pro"] == 0.414
    assert scores["together/deepseek-v4-pro"] == 0.414


def test_insert_source_value_adds_missing_key():
    text = (
        "models:\n"
        "  openai/gpt-5.6-sol:\n"
        "    sources:\n"
        "      deepswe: 0.727\n"
    )
    updated, changed = insert_source_value(text, "openai/gpt-5.6-sol", "arena_coding_elo", 1534.91)
    assert changed
    assert "arena_coding_elo: 1534.910" in updated
    assert "deepswe: 0.727" in updated


def test_parse_aa():
    payload = {"models": [{"slug": "deepseek-v4-pro", "intelligence_index": 62}]}
    scores = _parse_aa_payload(payload)
    assert scores["deepseek/deepseek-v4-pro"] == 62.0


def test_parse_aa_rejects_version_alias():
    payload = {"models": [{"slug": "deepseek-v4-pro-preview", "intelligence_index": 62}]}
    assert _parse_aa_payload(payload) == {}
