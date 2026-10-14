"""M3 工具执行器全量映射（doc 02 §4/§5 parity 矩阵）：24 工具 → bank-core 路径/参数/幂等键。

纯单测（StubBank 注入，离线可跑）；另含 /api/internal/notify → WS 推送链路（doc 03 §6.2）。
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.tools.bank_client import BankError
from app.tools.executor import run_tool
from app.tools.specs import TOOL_SPECS


class StubBank:
    """记录调用的假客户端；GET 返回可排序的 items 以支撑 recommend_wealth 后处理。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get(self, path, **params):
        self.calls.append(("GET", path, params))
        return {"items": [{"annual_yield": 2.8, "risk_level": 2, "id": "p001"},
                          {"annual_yield": 3.1, "risk_level": 2, "id": "p004"}], "total": 2}

    async def post(self, path, payload, idempotency_key=None):
        self.calls.append(("POST", path, payload, idempotency_key))
        return {"code": "OK"}


async def _run(name, args):
    stub = StubBank()
    out = await run_tool(name, args, stub)
    assert out["ok"] is True, out
    return stub.calls[-1]


# (tool, args, method, path, 关键 payload 断言)
CASES = [
    ("query_balance", {}, "GET", "/api/accounts", None),
    ("query_transactions", {"category": "餐饮"}, "GET", "/api/accounts/a001/transactions", None),
    ("resolve_contact", {"keyword": "李磊"}, "GET", "/api/contacts", None),
    ("change_password", {"old_password": "123456", "new_password": "Abcdef12"},
     "POST", "/api/auth/change-password", {"old_password": "123456", "new_password": "Abcdef12"}),
    ("transfer", {"to_contact_id": "c007", "amount": 200, "remark": "聚餐"},
     "POST", "/api/transfers", {"to_contact_id": "c007", "amount": 200, "remark": "聚餐"}),
    ("aa_split", {"total_amount": 300, "contact_ids": ["c005", "c006"]},
     "POST", "/api/transfers/aa-split", {"total_amount": 300, "contact_ids": ["c005", "c006"]}),
    ("analyze_billing", {"period": "2026-08", "kind": "category"}, "GET", "/api/billing/category-stats", None),
    ("detect_subscriptions", {}, "GET", "/api/subscriptions/detect", None),
    ("query_wealth_products", {"risk_max": 2}, "GET", "/api/wealth/products", None),
    ("query_holdings", {}, "GET", "/api/wealth/holdings", None),
    ("purchase_wealth", {"product_id": "p001", "amount": 5000},
     "POST", "/api/wealth/purchase", {"product_id": "p001", "amount": 5000}),
    ("redeem_wealth", {"holding_id": "h001", "amount": 5000},
     "POST", "/api/wealth/redeem", {"holding_id": "h001", "amount": 5000}),
    ("apply_virtual_card", {}, "POST", "/api/cards/apply-virtual", {}),
    ("adjust_card_limit", {"card_id": "cd002", "daily_limit": 8888},
     "POST", "/api/cards/cd002/limit", {"daily_limit": 8888}),
    ("freeze_card", {"card_id": "cd001"}, "POST", "/api/cards/cd001/freeze", {}),
    ("unfreeze_card", {"card_id": "cd001"}, "POST", "/api/cards/cd001/unfreeze", {}),
    ("report_card_loss", {"card_id": "cd001"}, "POST", "/api/cards/cd001/report-loss", {}),
    ("cancel_card_loss", {"card_id": "cd001"}, "POST", "/api/cards/cd001/cancel-loss", {}),
    ("cancel_subscription", {"subscription_id": "s003"}, "POST", "/api/subscriptions/s003/cancel", {}),
    ("freeze_funds", {"amount": 1000, "reason": "生日准备金"},
     "POST", "/api/accounts/a001/freeze-amount", {"amount": 1000, "reason": "生日准备金"}),
    ("unfreeze_funds", {"amount": 1000}, "POST", "/api/accounts/a001/unfreeze-amount", {"amount": 1000}),
    ("create_scheduled_task", {"type": "reminder", "run_at": "2026-10-14 09:00", "text": "明天爱人生日"},
     "POST", "/api/scheduled-tasks", None),
    ("place_gift_order", {"items": ["鲜花", "蛋糕"], "budget": 600, "run_at": "2026-10-13 10:00",
                          "recipient": "爱人", "merchant": "花加鲜花"},
     "POST", "/api/scheduled-tasks", None),
]


@pytest.mark.parametrize("tool,args,method,path,payload", CASES, ids=[c[0] for c in CASES])
def test_dispatch_mapping(tool, args, method, path, payload):
    call = asyncio.run(_run(tool, args))
    assert call[0] == method and call[1] == path, f"{tool} → {call[0]} {call[1]}"
    if payload is not None:
        assert call[2] == payload


def test_all_24_tools_covered():
    """parity：doc 02 §5 唯一清单 24 个，本文件逐一落地（recommend_wealth 走专项用例）。"""
    assert {c[0] for c in CASES} | {"recommend_wealth"} == set(TOOL_SPECS)


def test_analyze_billing_kind_variants():
    assert (asyncio.run(_run("analyze_billing", {"period": "2026-08", "kind": "anomalies"})))[1] == "/api/billing/anomalies"
    assert (asyncio.run(_run("analyze_billing", {"period": "2026-08", "kind": "report"})))[1] == "/api/billing/report"
    assert (asyncio.run(_run("analyze_billing", {"period": "2026-08"})))[1] == "/api/billing/category-stats"


def test_recommend_wealth_sorts_top5():
    stub = StubBank()
    out = asyncio.run(run_tool("recommend_wealth", {"risk_max": 2}, stub))
    assert out["ok"] and out["data"]["recommend"] is True
    assert [i["id"] for i in out["data"]["items"]] == ["p004", "p001"], "按年化降序推荐"
    assert stub.calls[0][0] == "GET" and stub.calls[0][1] == "/api/wealth/products"


def test_write_tools_carry_idempotency_key():
    for tool, args in [("transfer", {"to_contact_id": "c007", "amount": 1}),
                       ("purchase_wealth", {"product_id": "p001", "amount": 1000}),
                       ("redeem_wealth", {"holding_id": "h001", "amount": 1000})]:
        stub = StubBank()
        asyncio.run(run_tool(tool, {**args, "idempotency_key": "k-1"}, stub))
        assert stub.calls[-1][3] == "k-1", f"{tool} 幂等键透传"


def test_create_scheduled_task_collects_payload():
    stub = StubBank()
    asyncio.run(run_tool("create_scheduled_task",
                   {"type": "gift_order", "run_at": "2026-10-13", "items": ["鲜花"],
                    "amount": 200, "recipient": "爱人"}, stub))
    body = stub.calls[-1][2]
    assert body["task_type"] == "gift_order" and body["next_run_at"] == "2026-10-13"
    assert body["payload"] == {"items": ["鲜花"], "amount": 200, "recipient": "爱人"}


def test_bank_error_wrapped():
    class Boom(StubBank):
        async def get(self, path, **params):
            raise BankError("INSUFFICIENT_BALANCE", "余额不足", 400)
    out = asyncio.run(run_tool("query_balance", {}, Boom()))
    assert out["ok"] is False and out["error"]["code"] == "INSUFFICIENT_BALANCE"


# ── 通知回调（doc 03 §6.2）：bank-core 调度器 → agent → WS 推送 ──
@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_internal_notify_pushes_ws(client):
    with client.websocket_connect("/ws/web?session=it_notify") as ws:
        assert ws.receive_json()["type"] == "session_ready"
        r = client.post("/api/internal/notify", json={
            "user_id": "u001", "event_type": "task_executed",
            "title": "【智银】礼品订单已完成", "content": "已为爱人订购 鲜花、蛋糕，¥600.00",
            "trace_id": "task_st000001"})
        assert r.status_code == 200 and r.json()["delivered"] == 1
        msg = ws.receive_json()
        assert msg["type"] == "notify"
        assert msg["payload"]["title"] == "【智银】礼品订单已完成"
        assert "鲜花" in msg["payload"]["content"]


def test_internal_notify_offline_delivered_zero(client):
    r = client.post("/api/internal/notify", json={
        "user_id": "u_offline", "event_type": "task_executed", "title": "t", "content": "c"})
    assert r.status_code == 200 and r.json()["delivered"] == 0