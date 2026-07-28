from model_router.classifier import Classification, classify_messages
from model_router.sessions import SessionStore, apply_session_classification


def test_session_holds_task_on_weak_followup():
    prior_cls = classify_messages(
        [{"role": "user", "content": "Write a Python function to merge two lists."}]
    )
    assert prior_cls.task_type == "code_generation"
    store = SessionStore(ttl_seconds=600)
    store.set_task("s1", prior_cls)
    prior = store.get_task("s1")
    follow = Classification("general_chat", 0.55, ["default_chat"])
    merged = apply_session_classification(follow, prior=prior)
    assert merged.task_type == "code_generation"
    assert "session_task_hold" in merged.signals


def test_session_allows_confident_drift():
    prior = Classification("general_chat", 0.55, ["default_chat"])
    turn = Classification("reasoning_math", 0.9, ["reasoning_language"])
    merged = apply_session_classification(turn, prior=prior)
    assert merged.task_type == "reasoning_math"
    assert "session_task_drift" in merged.signals


def test_session_rollup_accumulates():
    store = SessionStore(ttl_seconds=600, rollup_path=None)
    store.record_event(
        session_id="abc",
        task_type="general_chat",
        selected_model="openai/gpt-4o-mini",
        latency_ms=10.0,
        prompt_tokens=5,
        completion_tokens=3,
        estimated_cost_usd=0.001,
        actual_cost_usd=0.001,
        frontier_cost_usd=0.01,
        cost_delta_vs_frontier_usd=-0.009,
        cache_hit=False,
        estimated_cached_tokens=0,
    )
    store.record_event(
        session_id="abc",
        task_type="general_chat",
        selected_model="openai/gpt-4o-mini",
        latency_ms=20.0,
        prompt_tokens=5,
        completion_tokens=3,
        estimated_cost_usd=0.001,
        actual_cost_usd=None,
        frontier_cost_usd=0.01,
        cost_delta_vs_frontier_usd=-0.009,
        cache_hit=True,
        estimated_cached_tokens=100,
        input_cost_per_m=1.0,
    )
    rollup = store.get_rollup("abc")
    assert rollup is not None
    assert rollup.request_count == 2
    assert rollup.prompt_tokens == 10
    assert rollup.cache_hits == 1
    assert rollup.estimated_cache_savings_usd > 0
