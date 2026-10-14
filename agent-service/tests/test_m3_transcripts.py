"""M3 六场景 transcript 验收（doc 05 M3 表 #1-#6 + doc 02 §8.2 日累计超额升红变体）。

逐场景走完整 transcript：规则意图（离线确定）→ 静态 DAG → 权限裁决（黄确认/红 MFA）
→ bank-core 执行 → 回复文案，断言 intent / plan 工具 / 银行落库 / 回复四层一致。

前置：bank-core 已在 127.0.0.1:8100 启动（同 test_m1_e2e）；不可达整文件 skip。
写真实演示库（与 M1 E2E 同惯例），可重复执行；演示前删 bank-core/data/bank.db 重置。
通知半环（bank→agent→WS 推送）由 test_executor_m3.py 覆盖；M3#6 断言 run-now
执行产物（detail / 真实支出流水 / notified 字段）与三类任务落库。
"""
import os
import re
import uuid
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

BANK = os.environ.get("BANK_CORE_URL", "http://127.0.0.1:8100")


def _bank_up() -> bool:
    try:
        return httpx.get(f"{BANK}/health", timeout=2.0, trust_env=False).status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _bank_up(), reason="bank-core 未启动（127.0.0.1:8100）")


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sid():
    return f"m3_{uuid.uuid4().hex[:6]}"


def _chat(client, sid, text):
    r = client.post("/api/chat", json={"session_id": sid, "text": text})
    assert r.status_code == 200
    return r.json()


def _of(messages, kind):
    return [m for m in messages if m.get("type") == kind]


def _final_text(messages) -> str:
    return "".join(m["payload"].get("text", "") for m in _of(messages, "final"))


def _tools_of(messages) -> list[str]:
    return [m["payload"]["tool"] for m in _of(messages, "tool_progress")]


def _drive(client, sid, out, max_steps=8):
    """接力黄确认/红 MFA 直至会话回 active；返回 (最终响应, 全过程消息)。"""
    seen = list(out.get("messages") or [])
    steps = 0
    while out.get("session_status") in ("waiting_confirm", "waiting_mfa"):
        steps += 1
        assert steps <= max_steps, f"接力超限停在 {out.get('session_status')}"
        if out["session_status"] == "waiting_confirm":
            card = _of(out["messages"], "confirm_card")[-1]["payload"]
            out = client.post("/api/confirm", json={"session_id": sid,
                               "action_id": card["action_id"], "approved": True}).json()
        else:
            mfa = _of(out["messages"], "mfa_request")[0]["payload"]
            code = re.search(r"(\d{6})",
                             _of(out["messages"], "mfa_sms")[0]["payload"]["content"]).group(1)
            out = client.post("/api/mfa", json={"session_id": sid,
                              "challenge_id": mfa["challenge_id"], "code": code}).json()
        seen += out.get("messages") or []
    assert out.get("session_status") == "active", out.get("session_status")
    return out, seen


def _bank_get(path, **params):
    return httpx.get(f"{BANK}{path}", params=params or None, timeout=10, trust_env=False).json()


def _bank_delete(path) -> None:
    httpx.delete(f"{BANK}{path}", timeout=10, trust_env=False)


def _checking() -> dict:
    return next(a for a in _bank_get("/api/accounts")["items"] if a["type"] == "checking")


def _prune_stale_tasks(keep_run_ats: set[str]) -> None:
    """清掉历史 transcript 残留的 active 任务（测试产物；演示前仍以重置 bank.db 为准）。"""
    for t in _bank_get("/api/scheduled-tasks").get("items") or []:
        if t.get("status") == "active" and t.get("next_run_at") not in keep_run_ats:
            _bank_delete(f"/api/scheduled-tasks/{t['id']}")


def _anchor_month() -> str:
    """种子异常埋点所在月（doc 03 §9.2 冻结于 2026-09，与系统时钟解耦）。

    演示数据是"冻结快照"（当月演示日 09-23），而宿主时钟会继续走；
    因此账单场景一律以数据自身的月份为锚，避免"这个月"落到无数据的未来月份。
    """
    rows = _bank_get("/api/accounts/a001/transactions",
                     **{"keyword": "数码商城", "page_size": 5})["items"]
    hit = next((t for t in rows if t["counterparty"] == "数码商城"), None)
    assert hit, rows
    return hit["created_at"][:7]


def test_m3_1_billing_category_and_anomalies(client, sid):
    """M3#1 账单分析：上月分类统计 + 凌晨 ¥4,999 异常高亮；审计链路齐。"""
    out = _chat(client, sid, "上个月钱花哪了")
    assert _tools_of(out["messages"]) == ["analyze_billing"], out["messages"]
    assert "共支出" in _final_text(out["messages"]), _final_text(out["messages"])
    assert out["session_status"] == "active"

    anchor = _anchor_month()
    out = _chat(client, sid, f"{anchor[:4]}年{int(anchor[5:7])}月有没有异常支出")
    assert _tools_of(out["messages"]) == ["analyze_billing"], out["messages"]
    reply = _final_text(out["messages"])
    assert "检测到" in reply and "笔可疑支出" in reply, reply
    # DoD：凌晨 ¥4,999（数码商城）被规则命中——reply 展示当期检测结果，
    # 具体锚点从 bank anomalies 直查（当期可能有更大金额异常项占据 reply 首位）。
    an = _bank_get("/api/billing/anomalies", period=anchor)
    hit = next((i for i in an["items"] if i["counterparty"] == "数码商城"
                and i["amount"] == 4999.0), None)
    assert hit and any("凌晨" in r for r in hit["reasons"]), an
    audit = client.get(f"/api/audit/{out['trace_id']}").json()
    assert {"intent", "plan", "decision", "tool_call", "reply"} <= set(audit["kinds"]), audit


def test_m3_2_wealth_recommend_r4_reject_r2_purchase(client, sid):
    """M3#2 理财：推荐仅 ≤R2；R4 申购被拒并提示（银行原文案）；R2 申购红 MFA 成功；持仓可查。"""
    out = _chat(client, sid, "帮我推荐稳健点的理财")
    assert _tools_of(out["messages"]) == ["recommend_wealth"], out["messages"]
    reply = _final_text(out["messages"])
    assert "为您推荐" in reply and "R2" in reply, reply
    assert "R3" not in reply and "R4" not in reply and "R5" not in reply, reply

    out = _chat(client, sid, "申购 1 万元成长精选股票型基金")
    cards = _of(out["messages"], "confirm_card")
    assert cards and cards[0]["payload"]["risk_level"] == "red", out   # 静态定级 RED；服务端硬校验在执行期
    out, seen = _drive(client, sid, out)                               # 确认 + MFA → 银行 403 → 中止
    errs = [m for m in _of(seen, "error")
            if m["payload"].get("code") == "RISK_LEVEL_EXCEEDED"]
    assert errs and "已拒绝申购" in errs[0]["payload"]["message"], seen
    reply = _final_text(seen)
    assert "已拒绝" in reply and "R4" in reply, reply   # 失败文案 = 银行原始提示（非笼统话术）
    assert out["session_status"] == "active"           # aborted 后会话恢复可用

    out = _chat(client, sid, "申购 1000 元稳健添利 30 天")
    cards = _of(out["messages"], "confirm_card")
    assert cards and cards[0]["payload"]["risk_level"] == "red", out
    out, seen = _drive(client, sid, out)
    assert "purchase_wealth" in _tools_of(seen), _tools_of(seen)
    reply = _final_text(seen)
    assert "已申购" in reply and "稳健添利 30 天" in reply, reply

    out = _chat(client, sid, "我持有哪些理财")
    reply = _final_text(out["messages"])
    assert "当前持仓" in reply and "稳健添利 30 天" in reply, reply

def test_m3_3_subscription_detect_and_cancel(client, sid):
    """M3#3 订阅管理：自动识别 ≥5 个（含云存储与 iCloud 遗忘候选）；一键取消生效（黄确认）。"""
    det = _bank_get("/api/subscriptions/detect")
    assert det["total"] >= 5 and det["new_candidates"] >= 1, det
    assert "云存储" in {i["merchant"] for i in det["items"]}, det

    out = _chat(client, sid, "我有哪些自动扣费的订阅")
    assert _tools_of(out["messages"]) == ["detect_subscriptions"], out["messages"]
    reply = _final_text(out["messages"])
    assert "检测到" in reply and "云存储" in reply and "68.00" in reply, reply
    assert out["session_status"] == "active"

    subs = _bank_get("/api/subscriptions")["items"]
    target = next(s for s in subs if s["merchant"] == "云存储")
    fresh = target["status"] == "生效"
    out = _chat(client, sid, "帮我取消云存储订阅")
    card = _of(out["messages"], "confirm_card")[0]["payload"]
    assert card["risk_level"] == "yellow", card
    out, seen = _drive(client, sid, out)
    assert "cancel_subscription" in _tools_of(seen), _tools_of(seen)
    reply = _final_text(seen)
    assert "已取消订阅" in reply, reply
    if fresh:
        assert "68.00" in reply, reply   # 重放时 changed=false → 每月可省 ¥0.00
    subs2 = _bank_get("/api/subscriptions")["items"]
    assert next(s for s in subs2 if s["id"] == target["id"])["status"] == "已取消"


def test_m3_4_card_lifecycle(client, sid):
    """M3#4 卡片管理：申请/调额/冻结（黄）+ 挂失/解挂（红 MFA）+ 解冻恢复，全通且银行状态一致。"""
    # 申请虚拟卡（黄）
    out = _chat(client, sid, "帮我申请一张虚拟卡")
    card = _of(out["messages"], "confirm_card")[0]["payload"]
    assert card["risk_level"] == "yellow", card
    assert any(d.get("value") == "apply_virtual_card" for d in card["detail"]), card
    out, seen = _drive(client, sid, out)
    reply = _final_text(seen)
    assert "6228" in reply and "正常" in reply, reply

    # 调额 8888（黄）：尾号 8899
    out = _chat(client, sid, "把卡额度调到 8888，尾号 8899 那张")
    card = _of(out["messages"], "confirm_card")[0]["payload"]
    assert card["risk_level"] == "yellow", card
    out, seen = _drive(client, sid, out)
    assert "adjust_card_limit" in _tools_of(seen), _tools_of(seen)
    reply = _final_text(seen)
    assert "8,888.00" in reply, reply
    cards = _bank_get("/api/cards")["items"]
    assert any("8899" in c["card_no_masked"] and c["daily_limit"] == 8888 for c in cards), cards

    # 冻结（黄）
    out = _chat(client, sid, "冻结卡片，尾号 8899")
    out, seen = _drive(client, sid, out)
    assert "freeze_card" in _tools_of(seen), _tools_of(seen)
    assert "「冻结」" in _final_text(seen), _final_text(seen)
    cards = _bank_get("/api/cards")["items"]
    assert next(c for c in cards if "8899" in c["card_no_masked"])["status"] == "冻结"

    # 挂失（红，MFA）
    out = _chat(client, sid, "我尾号 6688 的卡丢了，帮我挂失")
    card = _of(out["messages"], "confirm_card")[0]["payload"]
    assert card["risk_level"] == "red", card
    out, seen = _drive(client, sid, out)
    assert _of(seen, "mfa_request"), "挂失应下发 MFA"
    assert "report_card_loss" in _tools_of(seen), _tools_of(seen)
    assert "「挂失」" in _final_text(seen), _final_text(seen)
    cards = _bank_get("/api/cards")["items"]
    assert next(c for c in cards if "6688" in c["card_no_masked"])["status"] == "挂失"

    # 解挂（红 MFA）+ 解冻（黄）：状态机回正，保证可重复执行
    out = _chat(client, sid, "卡找到了，我尾号 6688 的卡帮我解挂")
    out, seen = _drive(client, sid, out)
    assert "cancel_card_loss" in _tools_of(seen), _tools_of(seen)
    out = _chat(client, sid, "解冻卡片，尾号 8899")
    out, seen = _drive(client, sid, out)
    assert "unfreeze_card" in _tools_of(seen), _tools_of(seen)
    cards = _bank_get("/api/cards")["items"]
    by_tail = {c["card_no_masked"][-4:]: c for c in cards}
    assert by_tail["6688"]["status"] == "正常" and by_tail["8899"]["status"] == "正常", by_tail

def test_m3_5_aa_split_two_requests(client, sid):
    """M3#5 AA 收款：「这顿 300 我们仨 AA」→ 人数解析（3-1=2）→ 2 笔收款单、每人 ¥100。"""
    out = _chat(client, sid, "这顿 300 我们仨 AA")
    audit = client.get(f"/api/audit/{out['trace_id']}").json()
    intents = [e["payload"] for e in audit["events"] if e["node"] == "intent"]
    slots = (intents[-1] if intents else {}).get("slots") or {}
    assert slots.get("member_count") == 2, slots
    assert slots.get("total_amount") == 300.0, slots
    out, seen = _drive(client, sid, out)
    assert "aa_split" in _tools_of(seen), _tools_of(seen)
    reply = _final_text(seen)
    assert "AA 收款单已生成 2 笔" in reply and "¥100.00" in reply, reply


def test_m3_6_birthday_cross_scenario_e2e(client, sid):
    """M3#6 演示主线：生日联动四件套逐节点黄确认 → 任务落库 + 资金锁定 →
    run-now 加速触发礼品下单，产生真实支出流水（通知半环见 test_executor_m3）。"""
    today = date.today()
    month, year = today.month % 12 + 1, today.year + (1 if today.month == 12 else 0)
    bday = date(year, month, 15)
    gift_at = f"{(bday - timedelta(days=2)).isoformat()} 09:00:00"
    remind_at = f"{(bday - timedelta(days=1)).isoformat()} 09:00:00"
    unlock_at = f"{bday.isoformat()} 20:00:00"
    _prune_stale_tasks({gift_at, remind_at, unlock_at})

    frozen_before = _checking()["frozen_amount"]
    out = _chat(client, sid, "下个月 15 号我爱人生日，帮我提前准备好")
    assert out["session_status"] == "waiting_confirm", out
    out, seen = _drive(client, sid, out)

    cards = [m["payload"] for m in _of(seen, "confirm_card")]
    tools = [next(d["value"] for d in c["detail"] if d.get("label") == "工具") for c in cards]
    assert tools == ["freeze_funds", "place_gift_order",
                     "create_scheduled_task", "create_scheduled_task"], tools
    assert all(c["risk_level"] == "yellow" for c in cards), [c["risk_level"] for c in cards]
    assert any("1000" in str(d.get("value")) for d in cards[0]["detail"]), cards[0]["detail"]
    assert not _of(seen, "mfa_request"), "四件套全黄，不应触发 MFA"
    reply = _final_text(seen)
    for kw in ("已锁定", "已预订礼品", "已创建提醒", "自动解冻"):
        assert kw in reply, (kw, reply)

    frozen_after = _checking()["frozen_amount"]
    assert round(frozen_after - frozen_before, 2) == 1000.0, (frozen_before, frozen_after)

    active = {t["task_type"]: t for t in _bank_get("/api/scheduled-tasks")["items"]
              if t["status"] == "active"}
    assert set(active) == {"gift_order", "reminder", "fund_unlock"}, active
    assert active["gift_order"]["next_run_at"] == gift_at, active
    assert active["reminder"]["next_run_at"] == remind_at, active
    assert active["fund_unlock"]["next_run_at"] == unlock_at, active
    assert set(active["gift_order"]["payload"].get("items") or []) == {"鲜花", "蛋糕"}, active

    # run-now 注入时间到生日前 2 天：礼品下单到期 → 扣款并产生真实支出流水
    bal_before = _checking()["balance"]
    run = httpx.post(f"{BANK}/api/admin/scheduler/run-now", params={"now": gift_at},
                     timeout=15, trust_env=False).json()
    ours = next(e for e in run["executed"] if e["task_id"] == active["gift_order"]["id"])
    assert ours["ok"] and "鲜花" in ours["detail"] and "notified" in ours, ours
    bal_after = _checking()["balance"]
    assert round(bal_before - bal_after, 2) == 600.0, (bal_before, bal_after)
    txns = _bank_get("/api/accounts/a001/transactions", keyword="礼品订购")["items"]
    assert any(t["amount"] == -600.0 and t["channel"] == "scheduler" for t in txns), txns

    audit = client.get(f"/api/audit/{out['trace_id']}").json()
    assert {"intent", "plan", "decision", "confirm", "tool_call", "reply"} <= set(audit["kinds"]), audit



def test_m3_extra_transfer_escalate_daily_limit(client, sid):
    """doc 02 §8.2 规则 1 E2E：当日累计转账 >¥1000 → 红色升档 + MFA，依据入 upgrade_reasons。"""
    out = _chat(client, sid, "给李磊转 1500")
    cl = _of(out["messages"], "clarify_options")
    assert cl, "两个李磊应触发同名消歧"
    out = _chat(client, sid, "尾号 3821")
    card = _of(out["messages"], "confirm_card")[0]["payload"]
    assert card["risk_level"] == "red", card
    assert any("当日累计" in r for r in card["upgrade_reasons"]), card["upgrade_reasons"]
    out, seen = _drive(client, sid, out)
    assert _of(seen, "receipt"), "确认 + MFA 后应有转账回执"
    reply = _final_text(seen)
    assert "已向 李磊 转账 ¥1,500.00" in reply, reply



def test_m3_7_pronoun_refill_same_amount_e2e(client, sid):
    """M3#7 上下文省略 E2E：「再给她转一次」→ 历史回填同收款人同金额（黄确认链路不断）。"""
    out = _chat(client, sid, "给王芳转 500")
    card = _of(out["messages"], "confirm_card")
    assert card, "首笔应出确认卡"
    out, _ = _drive(client, sid, out)

    out = _chat(client, sid, "再给她转一次")
    cards = _of(out["messages"], "confirm_card")
    assert cards, "代词回填后应直接出确认卡（无需追问）"
    assert cards[0]["payload"]["risk_level"] in ("yellow", "red"), cards[0]["payload"]
    assert any("王芳" in str(d.get("value")) for d in cards[0]["payload"]["detail"]), cards[0]["payload"]
    out, seen = _drive(client, sid, out)
    reply = _final_text(seen)
    assert "王芳" in reply and "500.00" in reply, reply


def test_m3_7_pronoun_refill_amount_override_e2e(client, sid):
    """M3#7 金额覆盖：「再给她转 300」→ 收款人回填、金额取本轮 300。"""
    out = _chat(client, sid, "给王芳转 500")
    out, _ = _drive(client, sid, out)

    out = _chat(client, sid, "再给她转 300")
    cards = _of(out["messages"], "confirm_card")
    assert cards, "代词+金额应直接出确认卡"
    out, seen = _drive(client, sid, out)
    reply = _final_text(seen)
    assert "王芳" in reply and "300.00" in reply, reply

