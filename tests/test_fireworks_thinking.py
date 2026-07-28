from model_router.litellm_backend import apply_provider_cache_hints


def test_fireworks_hide_thinking_adds_kwargs():
    _, _, extra = apply_provider_cache_hints(
        model="fireworks_ai/accounts/fireworks/models/kimi-k3",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        supports_prompt_caching=False,
        fireworks_hide_thinking=True,
    )
    assert extra["reasoning_effort"] == "none"
    assert extra["thinking"] == {"type": "disabled"}


def test_fireworks_hide_thinking_can_be_disabled():
    _, _, extra = apply_provider_cache_hints(
        model="fireworks_ai/accounts/fireworks/models/kimi-k3",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        supports_prompt_caching=False,
        fireworks_hide_thinking=False,
    )
    assert "reasoning_effort" not in extra
    assert "thinking" not in extra


def test_non_fireworks_no_thinking_kwargs():
    _, _, extra = apply_provider_cache_hints(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        supports_prompt_caching=False,
        fireworks_hide_thinking=True,
    )
    assert "reasoning_effort" not in extra
