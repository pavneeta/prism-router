from fastapi.testclient import TestClient

from model_router.gateway import app, _is_auto_model


def test_is_auto_model_holmes_openai_prefix():
    assert _is_auto_model("openai/auto", ["auto"])
    assert _is_auto_model("openai/model-router/auto", ["auto"])
    assert _is_auto_model("auto", ["auto"])
    assert not _is_auto_model("openai/gpt-4o", ["auto"])


def test_explain_accepts_openai_auto(monkeypatch):
    monkeypatch.setenv("MODEL_ROUTER_DRY_RUN", "true")
    client = TestClient(app)
    resp = client.post(
        "/v1/router/explain",
        json={
            "model": "openai/auto",
            "messages": [
                {
                    "role": "user",
                    "content": "Use tools to diagnose CrashLoopBackOff on payments",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "kubectl_logs", "parameters": {"type": "object"}},
                }
            ],
        },
        headers={"X-Session-Id": "holmes-test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("decision", {}).get("selected_model")
    assert data["classification"]["task_type"]
