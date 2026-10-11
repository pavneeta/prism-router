from model_router.config import (
    BenchmarksConfig,
    Deployment,
    ModelBenchmark,
    ModelsConfig,
    PolicyConfig,
)
from model_router.feedback import FeedbackAccuracy, FeedbackEvent, record_feedback
from model_router.policy import SelectionPolicy


def test_ewma_cost_nudge_prefers_passing_model():
    tracker = FeedbackAccuracy(alpha=0.5)
    for _ in range(6):
        tracker.observe(task_type="general_chat", model_id="failing", passed=False)
        tracker.observe(task_type="general_chat", model_id="passing", passed=True)

    policy_cfg = PolicyConfig(
        default_min_accuracy=0.0,
        provider_health_enabled=False,
        frontier_model="passing",
        safe_fallback_model="failing",
    )
    benches = BenchmarksConfig(
        models={
            "failing": ModelBenchmark(
                input_cost_per_m=0.10,
                output_cost_per_m=0.10,
                accuracy={"general_chat": 0.9},
            ),
            "passing": ModelBenchmark(
                input_cost_per_m=0.11,
                output_cost_per_m=0.11,
                accuracy={"general_chat": 0.9},
            ),
        }
    )
    models = ModelsConfig(
        deployments=[
            Deployment(id="failing", litellm_model="openai/failing"),
            Deployment(id="passing", litellm_model="openai/passing"),
        ]
    )
    policy = SelectionPolicy(policy=policy_cfg, benchmarks=benches, models=models)
    cold = policy.select(
        task_type="general_chat",
        classification_confidence=0.95,
        prompt_text="hello",
    )
    nudged = policy.select(
        task_type="general_chat",
        classification_confidence=0.95,
        prompt_text="hello",
        feedback_accuracy=tracker,
    )
    assert cold.selected_model == "failing"
    assert nudged.selected_model == "passing"
    assert tracker.cost_multiplier("general_chat", "failing") > 1.0
    assert tracker.cost_multiplier("general_chat", "passing") < 1.0


def test_feedback_jsonl_replays_into_ewma(tmp_path, monkeypatch):
    path = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("MODEL_ROUTER_FEEDBACK_PATH", str(path))
    from model_router.config import get_settings
    from model_router.feedback import reset_feedback_logger_for_tests

    get_settings.cache_clear()
    reset_feedback_logger_for_tests()
    record_feedback(
        FeedbackEvent(
            ts="t",
            session_id="s",
            outcome="pass",
            task_hint="code_generation",
            selected_model="minimax/minimax-m3",
        )
    )
    reset_feedback_logger_for_tests()
    from model_router.feedback import get_feedback_accuracy

    tracker = get_feedback_accuracy()
    assert tracker.pass_rate("code_generation", "minimax/minimax-m3") is not None
    reset_feedback_logger_for_tests()
    get_settings.cache_clear()
