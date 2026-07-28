from model_router.stress.scoring import score_response


def test_python_exec_pass():
    content = "```python\ndef add(a,b):\n    return a+b\n```"
    r = score_response(
        checks={"type": "python_exec", "setup": "", "call": "add(2,3)", "expect": 5},
        content=content,
        message={"content": content},
    )
    assert r["pass"] and r["score"] == 1.0


def test_answer_int():
    r = score_response(
        checks={"type": "answer_int", "expect": 72},
        content="Natalia sold 72 total.\nAnswer: 72",
        message={},
    )
    assert r["pass"]


def test_tool_call_args():
    msg = {
        "tool_calls": [
            {
                "function": {
                    "name": "kubectl_logs",
                    "arguments": '{"pod":"payments-7d9f","namespace":"prod"}',
                }
            }
        ]
    }
    r = score_response(
        checks={
            "type": "tool_call",
            "name": "kubectl_logs",
            "args_contains": {"pod": "payments", "namespace": "prod"},
        },
        content="",
        message=msg,
    )
    assert r["pass"]


def test_contains_all():
    r = score_response(
        checks={"type": "contains_all", "needles": ["Redis", "latency"]},
        content="Redis caused high latency.",
        message={},
    )
    assert r["pass"]
