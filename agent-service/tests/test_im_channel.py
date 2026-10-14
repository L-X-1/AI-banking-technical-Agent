"""M3#8 IM 渠道降级（doc 02 §10.2 / doc 04 §4.18）：归一化上行 + 整段文本下行。

离线可跑：归一化/渲染为纯函数单测；webhook 全流程用 DictBank 注入（不触达 bank-core）。
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.channels import im
from app.graph import agent_graph as g


def _post(client, sid, text, command=""):
    r = client.post("/api/im/webhook", json={"session_id": sid, "text": text, "command": command})
    assert r.status_code == 200
    return r.json()


# ── 归一化（纯函数）───────────────────────────────────────────
def test_im_normalize_user_message():
    assert im.normalize_inbound({"text": "给赵敏转 200"})["type"] == "user_message"


def test_im_normalize_confirm_digits():
    assert im.normalize_inbound({"text": "1"}) == {"type": "action_confirm", "approved": True, "text": "1"}
    assert im.normalize_inbound({"text": "2"})["approved"] is False


def test_im_normalize_mfa_code():
    up = im.normalize_inbound({"text": "139286"})
    assert up["type"] == "mfa_submit" and up["code"] == "139286"


def test_im_normalize_explicit_command_wins():
    assert im.normalize_inbound({"text": "1", "command": "mfa"})["type"] == "mfa_submit"
    assert im.normalize_inbound({"text": "xxx", "command": "cancel"})["approved"] is False


# ── 渲染（纯函数：服务端 payload 原样转文本）───────────────────
def test_im_render_confirm_card_downgrade():
    out = im.render_outbound({"type": "confirm_card", "payload": {
        "title": "转账确认", "risk_level": "yellow",
        "detail": [{"label": "收款人", "value": "赵敏"}, {"label": "金额", "value": "¥200.00"}],
        "consequence": "实时到账", "upgrade_reasons": []}})
    assert "回复 1 确认 / 2 取消" in out and "¥200.00" in out and "赵敏" in out


def test_im_render_mfa_and_receipt():
    assert "6 位数字" in im.render_outbound({"type": "mfa_request", "payload": {
        "target_masked": "138****6688", "attempts_left": 3}})
    receipt = im.render_outbound({"type": "receipt", "payload": {
        "title": "转账成功", "counterparty": "赵敏",
        "detail": [{"label": "交易号", "value": "t1"}, {"label": "余额", "value": "¥52,100.00"}]}})
    assert "转账成功" in receipt and "¥52,100.00" in receipt


def test_im_render_skips_process_events():
    """非流式降级：tool_progress / stream_token / status 不出现在 IM 文本里（doc 04 §4.18）。"""
    for kind in ("tool_progress", "stream_token", "status"):
        assert im.render_outbound({"type": kind, "payload": {"result_summary": "查联系人 1 位"}}) == ""
    assert im.render_batch([
        {"type": "tool_progress", "payload": {"result_summary": "内部过程"}},
        {"type": "final", "payload": {"text": "已到账"}},
    ]) == ["已到账"]


# ── webhook 全流程（DictBank；同一 trace、安全不降级）─────────
class DictBank:
    def __init__(self):
        self.calls = []

    async def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if path == "/api/accounts":
            return {"items": [{"id": "a001", "type": "checking", "balance": 52300.0}]}
        if path.startswith("/api/accounts/") and path.endswith("/transactions"):
            return {"items": [], "total": 0}   # 当日累计转账数据源（规则 1）
        if path == "/api/contacts":
            return {"items": [{"id": "c007", "name": "赵敏", "phone_tail": "2211",
                               "account_no_tail": "2211", "remark": "朋友"}]}
        raise AssertionError(path)

    async def post(self, path, payload, idempotency_key=None):
        self.calls.append(("POST", path, payload, idempotency_key))
        return {"code": "OK", "transaction_id": "t00001", "amount": payload.get("amount", 200),
                "counterparty": "赵敏", "balance_after": 52100.0}


@pytest.fixture()
def client():
    g.set_client_factory(DictBank)
    from app.main import app
    with TestClient(app) as c:
        yield c
    g.set_client_factory(None)


def test_im_webhook_transfer_confirm_flow(client):
    out = _post(client, "s_im_t7", "给赵敏转 200")
    assert out["session_status"] == "waiting_confirm", out
    assert any("回复 1 确认 / 2 取消" in t and "¥200.00" in t for t in out["replies"]), out
    assert out["trace_id"].startswith("tr_")

    out2 = _post(client, "s_im_t7", "1")
    assert out2["session_status"] == "active", out2
    assert any(t.startswith("【回执】") and "赵敏" in t for t in out2["replies"]), out2
    assert out2["trace_id"].startswith("tr_")   # 同一会话、每轮独立 trace（trace 体系一致）


def test_im_webhook_cancel_without_pending():
    from app.main import app
    with TestClient(app) as c:
        out = _post(c, "s_im_empty", "2")
    assert "ACTION_NOT_FOUND" in " ".join(out["replies"]), out


def test_im_page_served(client):
    r = client.get("/im")
    assert r.status_code == 200 and "模拟 IM" in r.text
