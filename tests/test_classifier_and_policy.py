import json
from pathlib import Path

from model_router.benchmarks import derive_task_accuracy, normalize_aa_index
from model_router.classifier import classify_messages
from model_router.config import (
    BenchmarksConfig,
    Deployment,
    ModelBenchmark,
    ModelsConfig,
    PolicyConfig,
    load_benchmarks,
    load_models,
    load_policy,
)
from model_router.litellm_backend import apply_provider_cache_hints
from model_router.policy import SelectionPolicy, estimate_input_tokens
from model_router.prompt_cache import PromptCacheLayer, SessionAffinity, get_prompt_cache


def test_classify_code_generation():
    result = classify_messages(
        [{"role": "user", "content": "Write a Python function that merges two sorted lists."}]
    )
    assert result.task_type == "code_generation"
    assert result.confidence >= 0.7


def test_classify_summarization():
    result = classify_messages(
        [{"role": "user", "content": "Please summarize this article into key points."}]
    )
    assert result.task_type == "summarization"


def test_classify_tools_present_ambiguous_nudges_tool_use():
    """Tools alone + weak chat content → tool_use_agent."""
    result = classify_messages(
        [{"role": "user", "content": "What's the weather?"}],
        tools=[{"type": "function", "function": {"name": "get_weather"}}],
    )
    assert result.task_type == "tool_use_agent"
    assert "tools_present" in result.signals
    assert "tools_nudge_ambiguous" in result.signals


def test_classify_tools_plus_coding_stays_code_generation():
    """Agent harnesses send tools every turn — coding content must win."""
    result = classify_messages(
        [{"role": "user", "content": "Write a Python function that merges two sorted lists."}],
        tools=[{"type": "function", "function": {"name": "run_terminal"}}],
    )
    assert result.task_type == "code_generation"
    assert "tools_present" in result.signals
    assert "code_generation_language" in result.signals


def test_classify_tools_plus_debug_stays_code_review():
    result = classify_messages(
        [{"role": "user", "content": "Fix the bug in this stack trace / exception."}],
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )
    assert result.task_type == "code_review_debug"
    assert "tools_present" in result.signals


def test_classify_extract_json_not_chat_or_math():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "From the text extract JSON with keys name and port only:\n\n"
                    "Service api-gateway listens on port 8080 in namespace edge."
                ),
            }
        ]
    )
    assert result.task_type == "extraction_qa"
    assert "extraction_language" in result.signals


def test_classify_extract_how_many_number_only_not_math():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "Incident started 2026-07-28T14:02:00Z and ended "
                    "2026-07-28T14:31:00Z. How many minutes did it last? Number only."
                ),
            }
        ]
    )
    assert result.task_type == "extraction_qa"


def test_classify_extract_according_to_yes_no():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "According to: 'fireworks_hide_thinking defaults to true in "
                    "policy.yaml'. Does Prism hide Fireworks thinking by default? "
                    "Answer yes or no."
                ),
            }
        ]
    )
    assert result.task_type == "extraction_qa"


def test_classify_creative_blurb_not_chat():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "Write a playful 4-sentence product blurb for an "
                    "intelligence-aware model router without using the words "
                    "'synergy' or 'revolutionary'."
                ),
            }
        ]
    )
    assert result.task_type == "creative_writing"


def test_classify_creative_warning_label():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "Write a stern two-sentence warning label for flipping models "
                    "mid-session and destroying the prompt cache."
                ),
            }
        ]
    )
    assert result.task_type == "creative_writing"


def test_classify_k8s_ops_is_tool_use():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "Investigate CrashLoopBackOff on pod payments-7d9f in namespace prod."
                ),
            }
        ]
    )
    assert result.task_type == "tool_use_agent"
    assert "k8s_ops" in result.signals


def test_difficulty_easy_for_simple_codegen():
    result = classify_messages(
        [{"role": "user", "content": "Write a Python function that merges two sorted lists."}]
    )
    assert result.task_type == "code_generation"
    assert result.difficulty == "easy"


def test_difficulty_hard_for_lru_and_async():
    lru = classify_messages(
        [
            {
                "role": "user",
                "content": (
                    "Implement a Python class LRUCache with O(1) average get/put."
                ),
            }
        ]
    )
    assert lru.task_type == "code_generation"
    assert lru.difficulty == "hard"
    dbg = classify_messages(
        [
            {
                "role": "user",
                "content": "Debug this async/await race condition in a multi-threaded cache.",
            }
        ]
    )
    assert dbg.task_type == "code_review_debug"
    assert dbg.difficulty == "hard"


def test_difficulty_hard_for_multi_tool_k8s():
    result = classify_messages(
        [
            {
                "role": "user",
                "content": "Use tools to diagnose ingress traffic failing in ns ecommerce.",
            }
        ],
        tools=[
            {"type": "function", "function": {"name": "kubectl_get"}},
            {"type": "function", "function": {"name": "kubectl_logs"}},
            {"type": "function", "function": {"name": "kubectl_describe"}},
        ],
    )
    assert result.task_type == "tool_use_agent"
    assert result.difficulty == "hard"


def test_multi_turn_uses_last_user_and_prior_task_signal():
    result = classify_messages(
        [
            {"role": "user", "content": "Write a Python function that merges two lists."},
            {"role": "assistant", "content": "def merge(a, b): ..."},
            {"role": "user", "content": "Add type hints."},
        ],
        prior_task="code_generation",
    )
    assert "multi_turn_last_user" in result.signals
    assert "prior_task:code_generation" in result.signals


def test_stress_scenarios_expect_task():
    path = Path("benchmarks/scenarios/v1/scenarios.jsonl")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    misses = []
    for row in rows:
        got = classify_messages(row["messages"], tools=row.get("tools"))
        if got.task_type != row["expect_task"]:
            misses.append((row["id"], row["expect_task"], got.task_type, got.signals))
    assert misses == []


def test_derive_accuracy_from_public_sources():
    acc = derive_task_accuracy(
        {
            "deepswe": 0.685,
            "terminal_bench_v2_1": 0.883,
            "aa_intelligence_index": 57,
            "arena_elo": 1500,
        }
    )
    assert acc["code_generation"] == 0.685
    assert acc["tool_use_agent"] == 0.883
    assert acc["reasoning_math"] == round(normalize_aa_index(57) or 0.0, 4)
    assert acc["general_chat"] > 0.8


def test_seed_benchmarks_include_leaderboard_models():
    """Structure / provenance checks — avoid pinning exact leaderboard floats."""
    import re

    benches = load_benchmarks()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", benches.snapshot_date or "")
    assert "moonshot/kimi-k3" in benches.models
    assert "openai/gpt-5.6-sol" in benches.models
    assert "anthropic/claude-opus-5" in benches.models
    assert "anthropic/claude-fable-5" in benches.models
    fable_deepswe = benches.models["anthropic/claude-fable-5"].sources.get("deepswe")
    assert fable_deepswe is not None
    assert 0.6 < float(fable_deepswe) <= 1.0

    kimi = benches.models["moonshot/kimi-k3"]
    assert "deepswe" in kimi.sources
    assert "terminal_bench_v2_1" in kimi.sources
    assert "aa_intelligence_index" in kimi.sources
    assert 0.0 < float(kimi.sources["deepswe"]) <= 1.0
    assert 0.0 < float(kimi.sources["terminal_bench_v2_1"]) <= 1.0
    assert "code_generation" in kimi.accuracy
    assert "tool_use_agent" in kimi.accuracy
    assert kimi.accuracy["code_generation"] == float(kimi.sources["deepswe"])
    assert kimi.accuracy["tool_use_agent"] == float(kimi.sources["terminal_bench_v2_1"])

    for mid in ("openai/gpt-5.6-sol", "anthropic/claude-opus-5", "zai/glm-5.2"):
        src = benches.models[mid].sources
        assert any(k in src for k in ("deepswe", "swe_bench_verified", "terminal_bench_v2_1"))


def test_derive_accuracy_prefers_deepswe_for_codegen():
    both = derive_task_accuracy({"deepswe": 0.685, "swe_bench_verified": 0.806})
    assert both["code_generation"] == 0.685
    assert both["code_review_debug"] == 0.806
    swe_only = derive_task_accuracy({"swe_bench_verified": 0.806})
    assert "code_generation" not in swe_only
    assert swe_only["code_review_debug"] == 0.806


def test_policy_chat_picks_cheapest_above_floor():
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    decision = policy.select(
        task_type="general_chat",
        classification_confidence=0.9,
        prompt_text="Hello, how are you?",
    )
    # Among enabled models clearing chat floor, gpt-4o-mini is cheapest
    assert decision.selected_model == "openai/gpt-4o-mini"
    assert decision.reason == "min_effective_cost_above_intelligence_floor"
    assert decision.cost_delta_vs_frontier_usd < 0


def test_policy_code_requires_strong_coding_scores():
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    decision = policy.select(
        task_type="code_generation",
        classification_confidence=0.9,
        prompt_text="Implement a binary search in Rust",
    )
    # Live-validated Together MiniMax clears the floor and is cheapest.
    assert decision.selected_model == "minimax/minimax-m3"
    assert decision.min_accuracy == 0.65
    assert "zai/glm-5.2" not in decision.eligible_models
    assert "zai/glm-5.3" not in decision.eligible_models
    assert "deepseek/deepseek-v4-pro" in decision.eligible_models
    # Together defaults remain passthrough-only until live validation is complete.
    assert "moonshot/kimi-k3" not in decision.eligible_models
    assert "anthropic/claude-fable-5" in decision.eligible_models
    assert decision.selected_accuracy >= 0.65


def test_policy_tool_use_prefers_terminal_bench_eligible():
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    decision = policy.select(
        task_type="tool_use_agent",
        classification_confidence=0.9,
        prompt_text="Use tools to diagnose the failing deploy",
        likely_prefix_reuse=True,
    )
    # Live-validated MiniMax tool-use score clears the floor at lowest cost.
    assert decision.selected_accuracy >= 0.70
    assert decision.min_accuracy == 0.70
    assert decision.selected_model == "minimax/minimax-m3"


def test_hard_codegen_floor_excludes_near_miss_keeps_easy_cheap():
    policy_cfg = PolicyConfig(
        default_min_accuracy=0.0,
        min_accuracy_by_task={"code_generation": 0.65},
        hard_accuracy_bump=0.05,
        hard_floor_tasks=["code_generation"],
        frontier_model="strong",
        safe_fallback_model="cheap",
        provider_health_enabled=False,
    )
    benches = BenchmarksConfig(
        models={
            "cheap": ModelBenchmark(
                input_cost_per_m=0.1,
                output_cost_per_m=0.1,
                accuracy={"code_generation": 0.67},
            ),
            "strong": ModelBenchmark(
                input_cost_per_m=2.0,
                output_cost_per_m=2.0,
                accuracy={"code_generation": 0.90},
            ),
        }
    )
    models = ModelsConfig(
        deployments=[
            Deployment(id="cheap", litellm_model="openai/cheap"),
            Deployment(id="strong", litellm_model="openai/strong"),
        ]
    )
    policy = SelectionPolicy(policy=policy_cfg, benchmarks=benches, models=models)
    easy = policy.select(
        task_type="code_generation",
        classification_confidence=0.9,
        prompt_text="Write a Python hello world.",
        difficulty="easy",
    )
    hard = policy.select(
        task_type="code_generation",
        classification_confidence=0.9,
        prompt_text="Implement an O(1) LRU cache.",
        difficulty="hard",
    )
    assert easy.selected_model == "cheap"
    assert easy.min_accuracy == 0.65
    assert hard.selected_model == "strong"
    assert hard.min_accuracy == 0.70


def test_session_affinity_preserves_model():
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    # Stick to gpt-4o-mini (cheapest eligible chat model) — affinity should preserve it
    affinity = SessionAffinity(
        model_id="openai/gpt-4o-mini",
        litellm_model="openai/gpt-4o-mini",
        prefix_tokens_estimate=2000,
        updated_at=0,
    )
    decision = policy.select(
        task_type="general_chat",
        classification_confidence=0.9,
        prompt_text="follow-up: tell me more " + ("x" * 8000),
        session_affinity=affinity,
    )
    assert decision.selected_model == "openai/gpt-4o-mini"
    assert decision.reason == "session_affinity_preserve_prompt_cache"


def test_sticky_cached_token_math_caps_at_prefix():
    """Cached tokens = min(in_tokens, prefix) * ratio — not max(prefix, in*ratio)."""
    from model_router.config import Deployment, ModelsConfig
    from model_router.policy import _estimate_cost

    policy_cfg = load_policy()
    benches = load_benchmarks()
    luna = benches.models["openai/gpt-5.6-luna"]
    prefix = 100
    in_tokens = 10_000
    ratio = policy_cfg.default_cache_hit_ratio
    expected_cached = int(min(in_tokens, prefix) * ratio)
    buggy_cached = min(in_tokens, max(prefix, int(in_tokens * ratio)))
    assert expected_cached == 70
    assert buggy_cached == 7000

    sticky_cost = _estimate_cost(
        luna, input_tokens=in_tokens, output_tokens=512, cached_tokens=expected_cached
    )
    buggy_cost = _estimate_cost(
        luna, input_tokens=in_tokens, output_tokens=512, cached_tokens=buggy_cached
    )
    assert sticky_cost > buggy_cost  # over-crediting made cost look too low

    affinity = SessionAffinity(
        model_id="openai/gpt-5.6-luna",
        litellm_model="openai/gpt-5.6-luna",
        prefix_tokens_estimate=prefix,
        updated_at=0,
    )
    # Luna-only so sticky path is observed regardless of cheaper cold rivals
    sticky_policy = SelectionPolicy(
        policy=policy_cfg,
        benchmarks=benches,
        models=ModelsConfig(
            deployments=[
                Deployment(id="openai/gpt-5.6-luna", litellm_model="openai/gpt-5.6-luna")
            ]
        ),
    )
    prompt_text = "follow-up " + ("x" * 40_000)
    decision = sticky_policy.select(
        task_type="general_chat",
        classification_confidence=0.9,
        prompt_text=prompt_text,
        session_affinity=affinity,
    )
    assert decision.selected_model == "openai/gpt-5.6-luna"
    assert decision.estimated_cached_tokens == int(
        min(estimate_input_tokens(prompt_text), prefix) * ratio
    )
    assert decision.reason == "session_affinity_preserve_prompt_cache"


def test_affinity_breaks_when_cold_wins_by_margin():
    """Tiny prefix → sticky cache savings negligible; cheap cold model wins."""
    policy = SelectionPolicy(
        policy=load_policy(),
        benchmarks=load_benchmarks(),
        models=load_models(),
    )
    affinity = SessionAffinity(
        model_id="anthropic/claude-opus-5",
        litellm_model="anthropic/claude-opus-5",
        prefix_tokens_estimate=1,
        updated_at=0,
    )
    decision = policy.select(
        task_type="general_chat",
        classification_confidence=0.9,
        prompt_text="Hello, how are you today?",
        session_affinity=affinity,
    )
    assert decision.selected_model == "openai/gpt-4o-mini"
    assert decision.reason == "min_effective_cost_above_intelligence_floor"
    assert decision.selected_model != affinity.model_id


def test_local_prompt_cache_roundtrip():
    cache = PromptCacheLayer(enabled=True, ttl_seconds=60)
    key = cache.request_key(
        model="moonshot/kimi-k3",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        temperature=0,
        max_tokens=16,
    )
    assert cache.get_local(key).hit is False
    cache.put_local(key, {"id": "cached", "choices": []})
    hit = cache.get_local(key)
    assert hit.hit is True
    assert hit.layer == "local"
    assert hit.response["id"] == "cached"


def test_get_prompt_cache_wires_policy_ttls():
    cache = get_prompt_cache()
    policy = load_policy()
    assert cache.enabled == policy.local_response_cache_enabled
    assert cache.ttl_seconds == policy.local_cache_ttl_seconds
    assert cache.affinity_ttl_seconds == policy.session_affinity_ttl_seconds


def test_provider_cache_hints_anthropic():
    messages = [
        {"role": "system", "content": "You are a coding agent."},
        {"role": "user", "content": "hi"},
    ]
    tools = [{"type": "function", "function": {"name": "bash"}}]
    out_msgs, out_tools, extra = apply_provider_cache_hints(
        model="anthropic/claude-sonnet-5",
        messages=messages,
        tools=tools,
        supports_prompt_caching=True,
        session_id="s1",
    )
    sys_content = out_msgs[0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[-1].get("cache_control", {}).get("type") == "ephemeral"
    assert out_tools is not None
    assert out_tools[-1].get("cache_control", {}).get("type") == "ephemeral"
    assert "cache_control_injection_points" in extra


def test_provider_cache_hints_openai_session_key():
    messages = [{"role": "user", "content": "hi"}]
    _, _, extra = apply_provider_cache_hints(
        model="openai/gpt-5.6-luna",
        messages=messages,
        tools=None,
        supports_prompt_caching=True,
        session_id="agent-1",
    )
    assert extra.get("prompt_cache_key") == "agent-1"


def test_provider_cache_hints_fireworks_session_affinity():
    messages = [{"role": "user", "content": "hi"}]
    _, _, extra = apply_provider_cache_hints(
        model="fireworks_ai/accounts/fireworks/models/deepseek-v4-pro",
        messages=messages,
        tools=None,
        supports_prompt_caching=True,
        session_id="fw-session-1",
        fireworks_hide_thinking=True,
    )
    assert extra.get("prompt_cache_key") == "fw-session-1"
    assert extra.get("extra_headers", {}).get("x-session-affinity") == "fw-session-1"
    assert extra.get("perf_metrics_in_response") is True
    assert extra.get("thinking") == {"type": "disabled"}


def test_provider_cache_hints_fireworks_skipped_without_session():
    _, _, extra = apply_provider_cache_hints(
        model="fireworks_ai/accounts/fireworks/models/kimi-k3",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        supports_prompt_caching=True,
        session_id=None,
        fireworks_hide_thinking=False,
    )
    assert "prompt_cache_key" not in extra
    assert "extra_headers" not in extra
    assert "perf_metrics_in_response" not in extra
