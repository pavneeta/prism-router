"""Unit tests for benchmark scraper payload parsers (no network)."""

from scripts.update_benchmarks import (
    SourceResult,
    _parse_aa_payload,
    _parse_arena_payload,
    _parse_swe_payload,
    _parse_swe_rebench_payload,
    _parse_terminal_payload,
    append_benchmark_model,
    append_deployment,
    apply_updates,
    extract_arena_ids,
    extract_deepswe_ids,
    insert_source_value,
    map_discovered_models,
    parse_fireworks_public_ids,
    parse_together_public_models,
    upsert_last_refresh,
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


def test_insert_source_value_expands_empty_mapping():
    text = (
        "models:\n"
        "  zai/glm-5.3:\n"
        "    sources: {}\n"
    )
    updated, changed = insert_source_value(text, "zai/glm-5.3", "deepswe", 0.51)
    assert changed
    assert "deepswe: 0.510" in updated
    assert "sources: {}" not in updated


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


def test_parse_together_docs_table_and_loose_ids():
    text = (
        "| Z.ai | GLM-5.3 | zai-org/GLM-5.3 | 1048575 | $1.40 | $0.26 | $4.40 | FP4 | Yes | Yes |\n"
        "also listed: deepseek-ai/DeepSeek-V4.1-Flash\n"
    )
    models = parse_together_public_models(text)
    assert models["zai-org/GLM-5.3"]["context_window"] == 1048575
    assert models["zai-org/GLM-5.3"]["input_cost_per_m"] == 1.40
    assert models["zai-org/GLM-5.3"]["cached_input_cost_per_m"] == 0.26
    assert models["zai-org/GLM-5.3"]["output_cost_per_m"] == 4.40
    assert "deepseek-ai/DeepSeek-V4.1-Flash" in models


def test_parse_fireworks_public_ids():
    text = (
        "Pinned IDs: `glm-5p3`, `glm-5p3-flash`, and "
        "accounts/fireworks/models/deepseek-v4p1-flash"
    )
    ids = parse_fireworks_public_ids(text)
    assert "glm-5p3" in ids
    assert "glm-5p3-flash" in ids
    assert "deepseek-v4p1-flash" in ids


def test_extract_leaderboard_ids():
    assert extract_deepswe_ids({"rows": [{"model": "glm-5.3"}, {"model": "kimi-k3"}]}) == [
        "glm-5.3",
        "kimi-k3",
    ]
    arena = {
        "rows": [
            {"row": {"model_name": "glm-5.3-max", "category": "overall"}},
            {"row": {"model_name": "claude-opus-5-max", "category": "coding"}},
        ]
    }
    assert extract_arena_ids(arena) == ["claude-opus-5-max", "glm-5.3-max"]


def test_map_together_glm_53_without_inventing_scores():
    proposals = map_discovered_models(
        existing_ids=set(),
        together_ids=["zai-org/GLM-5.3"],
        deepswe_ids=[],
        arena_ids=[],
        fireworks_ids=[],
    )
    assert len(proposals) == 1
    assert proposals[0]["catalog_id"] == "zai/glm-5.3"
    assert proposals[0]["litellm_model"] == "together_ai/zai-org/GLM-5.3"
    assert proposals[0]["auto_select"] is False
    assert proposals[0]["sources"] == {}
    assert "pending" in proposals[0]["notes"]


def test_map_attaches_real_deepswe_only():
    proposals = map_discovered_models(
        existing_ids=set(),
        together_ids=["zai-org/GLM-5.3"],
        deepswe_ids=["glm-5.3"],
        arena_ids=[],
        fireworks_ids=[],
        public_scores={"zai/glm-5.3": {"deepswe": 0.51}},
    )
    assert proposals[0]["sources"] == {"deepswe": 0.51}


def test_map_skips_unknown_and_existing_ids():
    assert (
        map_discovered_models(
            existing_ids=set(),
            together_ids=["acme/random-model"],
            deepswe_ids=["totally-unknown"],
            arena_ids=[],
            fireworks_ids=[],
        )
        == []
    )
    assert (
        map_discovered_models(
            existing_ids={"zai/glm-5.3"},
            together_ids=["zai-org/GLM-5.3"],
            deepswe_ids=[],
            arena_ids=[],
            fireworks_ids=[],
        )
        == []
    )


def test_apply_updates_bumps_snapshot_when_all_sources_fail():
    text = (
        'snapshot_date: "2026-01-01"\n'
        "models:\n"
        "  openai/gpt-4o:\n"
        "    sources:\n"
        "      deepswe: 0.500\n"
    )
    results = [SourceResult("deepswe", False, "skip: timeout")]
    updated, changes, notes = apply_updates(text, results, "2026-10-11")
    assert 'snapshot_date: "2026-10-11"' in updated
    assert any(c.model_id == "_meta" and c.source_key == "snapshot_date" for c in changes)
    assert any("skipped" in note for note in notes)
    assert "deepswe: 0.500" in updated


def test_upsert_last_refresh_always_rewrites():
    text = 'snapshot_date: "2026-01-01"\nmodels: {}\n'
    updated, changed = upsert_last_refresh(
        text,
        {"attempted_at": "2026-10-11T06:00:00Z", "sources_skipped": {"aa": "no key"}},
    )
    assert changed
    assert "attempted_at: '2026-10-11T06:00:00Z'" in updated or "2026-10-11T06:00:00Z" in updated
    assert "sources_skipped" in updated


def test_append_passthrough_rows():
    models = "deployments:\n  - id: zai/glm-5.2\n    litellm_model: together_ai/zai-org/GLM-5.2\n"
    benches = "models:\n  zai/glm-5.2:\n    sources:\n      deepswe: 0.438\n"
    models, added_m = append_deployment(models, "zai/glm-5.3", "together_ai/zai-org/GLM-5.3")
    benches, added_b = append_benchmark_model(
        benches,
        "zai/glm-5.3",
        context_window=1048575,
        input_cost_per_m=1.4,
        output_cost_per_m=4.4,
        cached_input_cost_per_m=0.26,
        sources={},
        notes="pending public scores; passthrough only",
    )
    assert added_m and added_b
    assert "id: zai/glm-5.3" in models
    assert "auto_select: false" in models
    assert "zai/glm-5.3:" in benches
    assert "sources: {}" in benches
    assert "deepswe:" not in benches.split("zai/glm-5.3:", 1)[1]


def test_seeded_glm_53_is_passthrough_without_invented_scores():
    from model_router.config import load_benchmarks, load_models

    dep = next(d for d in load_models().deployments if d.id == "zai/glm-5.3")
    assert dep.auto_select is False
    assert dep.litellm_model == "together_ai/zai-org/GLM-5.3"
    bench = load_benchmarks().models["zai/glm-5.3"]
    assert bench.sources.get("deepswe") is None
    assert bench.sources.get("swe_bench_verified") is None
    assert "pending" in (bench.notes or "")
