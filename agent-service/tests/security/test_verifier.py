"""M2#2 幻觉校验（doc 05 DoD #2）：工具未返回的数值出现在回复 → 阻断重生成 → 保守话术。

E2E 走离线 FakeBank + 渲染器注入，不依赖 bank-core。
"""
from _helpers import FakeBank, final_texts, new_sid, of, record
from app.security.audit import audit
from app.security.verifier import CONSERVATIVE_REPLY, OutputVerifier


def _chat(client, sid, text):
    return client.post("/api/chat", json={"session_id": sid, "text": text}).json()


def _verifier_event(trace_id):
    ev = [e for e in audit.fetch(trace_id)
          if e["node"] == "decision" and e["payload"].get("stage") == "verifier"]
    return ev[-1]["payload"] if ev else None


def test_blocks_number_absent_from_tool_results():
    r = OutputVerifier().verify("您的余额是 ¥99,999.00。", {})
    ok = (not r.passed and "99999" in r.hallucinated_numbers)
    record("verifier.工具无数值即阻断", "幻觉校验", ok, f"hallucinated={r.hallucinated_numbers}")
    assert ok


def test_passes_when_all_numbers_trace_to_tool_results():
    results = {"n1": {"ok": True, "data": {"items": [{"type": "checking", "balance": 52300.0}]}}}
    r = OutputVerifier().verify("您的活期账户余额为 ¥52,300.00。", results)
    record("verifier.数值可追溯即放行", "幻觉校验", r.passed, f"hallucinated={r.hallucinated_numbers}")
    assert r.passed and not r.hallucinated_numbers


def test_counts_list_length_as_ground_truth():
    results = {"n1": {"ok": True, "data": {"requests": [{"id": "r1"}, {"id": "r2"}],
                                           "share": 100.0}}}
    r = OutputVerifier().verify("AA 收款单已生成 2 笔，每人 ¥100.00。", results)
    record("verifier.列表计数合法引用", "幻觉校验", r.passed, "")
    assert r.passed


def test_e2e_hallucinated_reply_regenerated(client, use_fake_bank, sid):
    """doc 05 M2#2：工具未返回余额却回复余额 → 阻断 + 重生成（数值回到真实工具结果）。"""
    use_fake_bank(FakeBank())
    import app.graph.agent_graph as ag
    orig = ag._render_reply_parts
    ag._render_reply_parts = lambda st: (["您的活期账户余额为 ¥88,888.00。"], [])
    try:
        out = _chat(client, sid, "我的余额")
    finally:
        ag._render_reply_parts = orig
    text = " ".join(final_texts(out))
    ev = _verifier_event(out["trace_id"])
    ok = ("88,888" not in text and "43,210.55" in text
          and ev and ev["passed"] and ev["attempts"] == 2 and ev["regenerated"]
          and "88888" in ev["hallucinated_numbers"])
    record("verifier.E2E阻断并重生成", "幻觉校验", bool(ok),
           f"final含真实余额43,210.55、剔除88888；attempts={ev and ev['attempts']}")
    assert ok, (text, ev)


def test_e2e_conservative_fallback_after_two_failures(client, use_fake_bank, sid):
    """doc 03 §10：重生成 ≤2 次仍失败 → 保守话术（不含任何可校验数值）。"""
    use_fake_bank(FakeBank())
    import app.graph.agent_graph as ag
    orig_render, orig_safe = ag._render_reply_parts, ag._safe_reply
    ag._render_reply_parts = lambda st: (["您的活期账户余额为 ¥88,888.00。"], [])
    ag._safe_reply = lambda results: "最新余额 ¥88,888.00，另有定期 ¥100,000。"
    try:
        out = _chat(client, sid, "我的余额")
    finally:
        ag._render_reply_parts, ag._safe_reply = orig_render, orig_safe
    text = " ".join(final_texts(out))
    ev = _verifier_event(out["trace_id"])
    ok = (text == CONSERVATIVE_REPLY and ev and not ev["passed"] and ev["attempts"] == 3)
    record("verifier.E2E保守话术兜底", "幻觉校验", bool(ok),
           f"attempts={ev and ev['attempts']} final={text[:24]}")
    assert ok, (text, ev)
    record_reply_audit = any(e["node"] == "reply" for e in audit.fetch(out["trace_id"]))
    assert record_reply_audit
