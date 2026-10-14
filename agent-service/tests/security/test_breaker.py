"""M2#3 异常熔断（doc 05 DoD #3）：四触发状态机 + 15 分钟锁定 + 凌晨大额升红。

单测覆盖四触发与状态迁移；E2E 走离线 FakeBank 驱动真实图链路。
"""
import pytest

from _helpers import FakeBank, final_texts, new_sid, of, record
from app.security.audit import audit
from app.security.breaker import (FAIL_STREAK_LIMIT, INJECTION_LIMIT, LOCK_TTL_SEC,
                                  NIGHT_LARGE_LIMIT, CircuitBreaker, night_risk)
from app.security.permission import decide


@pytest.fixture()
def b(tmp_path):
    return CircuitBreaker(str(tmp_path / "agent.db"))


def _chat(client, sid, text):
    return client.post("/api/chat", json={"session_id": sid, "text": text}).json()


# ── 单测：四触发 ─────────────────────────────────────────────
def test_t1_three_tool_failures_open_write_scope(b):
    sid = "unit_t1"
    for _ in range(FAIL_STREAK_LIMIT - 1):
        b.record(sid, "tool_fail")
        assert not b.status(sid)["write_disabled"]
    b.record(sid, "tool_fail")
    st = b.status(sid)
    ok = st["state"] == "open" and st["scope"] == "write" and st["write_disabled"] and not st["locked"]
    record("熔断T1.连败3次禁写", "异常熔断", ok, f"state={st['state']} scope={st['scope']}")
    assert ok


def test_t1_recovery_via_half_open_probe(b):
    sid = "unit_t1_rec"
    for _ in range(FAIL_STREAK_LIMIT):
        b.record(sid, "tool_fail")
    b.record(sid, "tool_ok")                       # open(write) 期间查询成功不清锁
    assert b.status(sid)["write_disabled"], "open 期不得被一次查询直接恢复"
    base = b._now
    b._now = lambda: base() + LOCK_TTL_SEC + 1     # 到期 → half_open（仍禁写，待探测）
    st = b.status(sid)
    assert st["state"] == "half_open" and not st["locked"] and st["write_disabled"]
    b.record(sid, "tool_ok")                       # 半开探测成功 → closed（写恢复）
    st2 = b.status(sid)
    ok = st2["state"] == "closed" and not st2["write_disabled"]
    record("熔断T1.half_open探测恢复", "异常熔断", ok, "open→到期half_open→成功closed")
    assert ok


def test_t2_three_mfa_failures_lock_15min(b):
    sid = "unit_t2"
    for _ in range(FAIL_STREAK_LIMIT - 1):
        b.record(sid, "mfa_fail")
        assert not b.is_locked(sid)
    b.record(sid, "mfa_fail")
    st = b.status(sid)
    ok = (b.is_locked(sid) and st["trigger"] == "mfa_fail"
          and 0 < st["seconds_left"] <= LOCK_TTL_SEC and "15" in st["reason"])
    record("熔断T2.MFA连败3锁15min", "异常熔断", ok, f"left={st['seconds_left']}s")
    assert ok
    b.reset(sid)                                   # 重新登录解锁出口
    assert not b.is_locked(sid)


def test_t3_two_injection_hits_lock_session(b):
    sid = "unit_t3"
    for _ in range(INJECTION_LIMIT - 1):
        b.record(sid, "injection")
        assert not b.is_locked(sid)
    b.record(sid, "injection")
    st = b.status(sid)
    ok = b.is_locked(sid) and st["trigger"] == "injection"
    record("熔断T3.注入×2锁定", "异常熔断", ok, f"left={st['seconds_left']}s")
    assert ok


def test_t4_night_large_upgrades_red():
    """T4：凌晨 1-5 点 + 单笔 ≥¥2000 写操作 → 升红；白天/小额不触发。"""
    assert night_risk(1, NIGHT_LARGE_LIMIT, True) and night_risk(5, 5000, True)
    assert not night_risk(6, 5000, True) and not night_risk(2, 1999.99, True)
    assert not night_risk(3, 5000, False), "非写操作不触发"
    # 转账：凌晨时审计须留下 T4 依据（即使每日累计已升红）
    night = decide("transfer", {"amount": 2500}, {"today_transfer_total": 0, "hour": 3})
    day = decide("transfer", {"amount": 2500}, {"today_transfer_total": 0, "hour": 13})
    # 非转账写工具（freeze_funds 静态黄）：T4 是唯一升红来源
    sole = decide("freeze_funds", {"amount": 2500}, {"hour": 3})
    small = decide("freeze_funds", {"amount": 500}, {"hour": 3})
    ok = (night.level == "red" and any("凌晨" in r for r in night.reasons)
          and day.level == "red" and not any("凌晨" in r for r in day.reasons)
          and sole.level == "red" and any("熔断 T4" in r for r in sole.reasons)
          and small.level == "yellow")
    record("熔断T4.凌晨大额升红", "异常熔断", ok,
           "01-05点≥¥2000→红(含T4依据)；白天/小额不触发")
    assert ok


def test_permission_write_disabled_denies_writes_only():
    denied = decide("transfer", {"amount": 100}, {"write_disabled": True})
    allowed = decide("query_balance", {}, {"write_disabled": True})
    ok = (denied.denied and denied.code == "RISK_DENIED"
          and any("熔断" in r for r in denied.reasons) and not allowed.denied)
    record("熔断T1.禁写不误伤查询", "异常熔断", ok, "write→deny(RISK_DENIED)；query→green")
    assert ok


# ── E2E：离线 FakeBank 驱动真实链路 ──────────────────────────
def test_e2e_tool_failures_disable_writes_then_recover(client, use_fake_bank, sid):
    use_fake_bank(FakeBank(fail_get=True))
    for _ in range(FAIL_STREAK_LIMIT):
        out = _chat(client, sid, "我的余额")
        assert of(out["messages"], "error"), "工具失败应报错"
    from app.security.breaker import breaker
    st = breaker.status(sid)
    assert st["write_disabled"] and st["state"] == "open", st
    ev3 = [e for e in audit.fetch(out["trace_id"])
           if e["node"] == "decision" and e["payload"].get("stage") == "breaker"]
    assert ev3, "第 3 次连败应写 breaker 审计"
    record("熔断T1.E2E连败审计", "异常熔断", True, f"reason={ev3[0]['payload']['reason'][:30]}")

    use_fake_bank(FakeBank())                       # 核心恢复：查询可用、写仍禁用
    q = _chat(client, sid, "我的余额")
    assert "43,210.55" in " ".join(final_texts(q)), "查询类不应被禁"
    denied = _chat(client, sid, "给赵敏转 100")
    errs = [m for m in of(denied["messages"], "error")
            if m["payload"].get("code") == "RISK_DENIED"]
    ok = bool(errs) and "熔断" in errs[0]["payload"]["message"]
    record("熔断T1.E2E写操作被拒", "异常熔断", ok, errs[0]["payload"]["message"] if errs else "-")
    assert ok

    breaker.reset(sid)                              # 人工接管/解锁 → 写恢复
    after = _chat(client, sid, "给赵敏转 100")
    card = of(after["messages"], "confirm_card")
    assert card and card[0]["payload"]["risk_level"] == "yellow"
    client.post("/api/confirm", json={"session_id": sid,
                                      "action_id": card[0]["payload"]["action_id"],
                                      "approved": False})
    record("熔断T1.人工解锁恢复写", "异常熔断", True, "reset 后恢复确认卡链路")


def test_e2e_mfa_three_failures_lock_with_countdown(client, use_fake_bank, sid):
    use_fake_bank(FakeBank())
    out = _chat(client, sid, "给李磊转 5000")
    assert of(out["messages"], "clarify_options"), "同名消歧应触发"
    out = _chat(client, sid, "尾号 3821")
    card = of(out["messages"], "confirm_card")[0]
    assert card["payload"]["risk_level"] == "red"
    res = client.post("/api/confirm", json={"session_id": sid,
                                            "action_id": card["payload"]["action_id"],
                                            "approved": True}).json()
    mfa = of(res["messages"], "mfa_request")[0]["payload"]["challenge_id"]
    sms = of(res["messages"], "mfa_sms")[0]["payload"]["content"]
    code = next(w for w in sms.replace("，", " ").split() if w.isdigit() and len(w) == 6)
    wrong = ("9" if code[0] != "9" else "8") + code[1:]

    r1 = client.post("/api/mfa", json={"session_id": sid, "challenge_id": mfa, "code": wrong}).json()
    assert any(m["payload"].get("code") == "MFA_MISMATCH" for m in of(r1["messages"], "error"))
    r2 = client.post("/api/mfa", json={"session_id": sid, "challenge_id": mfa, "code": wrong}).json()
    assert of(r2["messages"], "error"), "第二次错码仍应报错"
    r3 = client.post("/api/mfa", json={"session_id": sid, "challenge_id": mfa, "code": wrong}).json()
    lock_errs = [m for m in of(r3["messages"], "error")
                 if m["payload"].get("code") == "SESSION_LOCKED"]
    from app.security.breaker import breaker
    st = breaker.status(sid)
    ok = (bool(lock_errs) and 0 < lock_errs[0]["payload"]["seconds_left"] <= LOCK_TTL_SEC
          and st["locked"] and st["trigger"] == "mfa_fail")
    record("熔断T2.E2E三次错码锁定", "异常熔断", ok,
           f"left={st['seconds_left']}s trigger={st['trigger']}")
    assert ok, (lock_errs, st)

    blocked = _chat(client, sid, "我的余额")        # 锁定期间一切输入被 guard 拒绝
    assert any(m["payload"].get("code") == "SESSION_LOCKED"
               for m in of(blocked["messages"], "error"))
    ev = [e for e in audit.fetch(blocked["trace_id"])
          if e["node"] == "decision" and e["payload"].get("breaker_locked")]
    assert ev and ev[0]["payload"]["trigger"] == "mfa_fail"
    record("熔断T2.E2E锁定期拦截+审计", "异常熔断", True, "guard_in SESSION_LOCKED 留痕")

