"""Offline CPT-style routing distribution (no GPU / no network)."""

from model_router.cpt_eval import run_eval


def test_cpt_routing_distribution():
    rows = run_eval()
    assert len(rows) >= 5

    for r in rows:
        if r["expect_task"]:
            assert r["task_type"] == r["expect_task"], r

    # Tools + coding content must stay on code tasks (harness realism)
    code_with_tools = [r for r in rows if r["name"] == "code_gen_with_tools"]
    assert code_with_tools[0]["task_type"] == "code_generation"

    cheap = sum(1 for r in rows if r["bucket"] == "cheap")
    assert cheap >= 1, rows

    chat = [r for r in rows if r["task_type"] == "general_chat"]
    assert chat and chat[0]["bucket"] == "cheap"
