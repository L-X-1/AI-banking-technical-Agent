"""会话快照（doc 04 §7 快照恢复）：刷新/断线重连后待办确认卡与 MFA 原样恢复。
离线可跑：DictBank 注入（不触达 bank-core）。
"""
import pytest
from fastapi.testclient import TestClient

from app.graph import agent_graph as g


class DictBank:
    def __init__(self):
        self.calls = []

    async def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if path == "/api/accounts":
            return {"items": [{"id": "a001", "type": "checking", "balance": 52300.0}]}
        if path.startswith("/api/accounts/") and path.endswith("/transactions"):
            return {"items": [], "total": 0}   # 当日累计为 0（升红判定数据源）
        if path == "/api/contacts":
            return {"items": [{"id": "c007", "name": "赵敏", "phone_tail": "2211",
                               "account_no_tail": "2211", "remark": "朋友"}]}
        raise AssertionError(path)

    async def post(self, path, payload, idempotency_key=None):
        self.calls.append(("POST", path, payload, idempotency_key))
        return {"code": "OK", "transaction_id": "t1", "amount": payload.get("amount"),
                "counterparty": "赵敏", "balance_after": 52000.0}


@pytest.fixture(scope="module")
def client():
    g.set_client_factory(DictBank)
    from app.main import app
    with TestClient(app) as c:
        yield c
    g.set_client_factory(None)


def _chat(client, sid, text):
    return client.post("/api/chat", json={"session_id": sid, "text": text}).json()


def _card_of(out):
    return [m for m in out["messages"] if m["type"] == "confirm_card"][0]["payload"]


def test_snapshot_recovers_pending_card(client):
    sid = "snap_t1"
    out = _chat(client, sid, "给赵敏转 200")
    card = _card_of(out)
    snap = client.get(f"/api/session/{sid}").json()
    assert snap["session_status"] == "waiting_confirm" and snap["card"], snap
    assert snap["card"]["action_id"] == card["action_id"]
    assert snap["card"]["detail"] == card["detail"]        # 服务端原样重放，非前端推断
    assert 0 < snap["card"]["expires_in_sec"] <= 300       # 倒计时双轨：服务端权威
    assert snap["mfa"] is None


def test_snapshot_recovers_mfa_then_clears(client):
    sid = "snap_t2"
    out = _chat(client, sid, "给赵敏转 1500")               # >当日阈值 ¥1000 → 红 → 确认 + MFA
    card = _card_of(out)
    assert card["risk_level"] == "red", card
    res = client.post("/api/confirm", json={"session_id": sid,
                                            "action_id": card["action_id"], "approved": True}).json()
    assert res["session_status"] == "waiting_mfa", res
    snap = client.get(f"/api/session/{sid}").json()
    assert snap["session_status"] == "waiting_mfa" and snap["mfa"], snap
    assert snap["mfa"]["attempts_left"] == 3 and len(snap["mfa"]["code"]) == 6
    done = client.post("/api/mfa", json={"session_id": sid,
                                         "challenge_id": snap["mfa"]["challenge_id"],
                                         "code": snap["mfa"]["code"]}).json()
    assert done["session_status"] == "active", done
    snap2 = client.get(f"/api/session/{sid}").json()
    assert snap2["session_status"] == "active" and snap2["mfa"] is None and snap2["card"] is None


def test_snapshot_unknown_session_is_active(client):
    snap = client.get("/api/session/snap_none").json()
    assert snap["session_status"] == "active" and snap["card"] is None and snap["mfa"] is None


def test_ws_pushes_snapshot_on_connect(client):
    sid = "snap_t3"
    out = _chat(client, sid, "给赵敏转 200")
    card = _card_of(out)
    with client.websocket_connect(f"/ws/web?session={sid}") as ws:
        assert ws.receive_json()["type"] == "session_ready"
        snap = ws.receive_json()
        assert snap["type"] == "session_snapshot", snap
        assert snap["payload"]["card"]["action_id"] == card["action_id"]


def test_ws_no_snapshot_when_nothing_pending(client):
    with client.websocket_connect("/ws/web?session=snap_clean") as ws:
        assert ws.receive_json()["type"] == "session_ready"
        ws.send_json({"type": "user_message", "text": "我的余额"})
        first = ws.receive_json()
        assert first["type"] != "session_snapshot", first


def test_interrupt_closes_pending_card(client):
    """doc 06 §3.5 规则 1：Esc 中断 → 待办关闭、会话回 active、旧确认不可再提交。"""
    sid = "snap_int"
    out = _chat(client, sid, "给赵敏转 200")
    card = _card_of(out)
    assert client.get(f"/api/session/{sid}").json()["card"]["action_id"] == card["action_id"]
    with client.websocket_connect(f"/ws/web?session={sid}") as ws:
        assert ws.receive_json()["type"] == "session_ready"
        assert ws.receive_json()["type"] == "session_snapshot"       # 待办卡随连接恢复
        ws.send_json({"type": "interrupt", "mode": "stop"})
        got = []
        while True:
            m = ws.receive_json()
            got.append(m)
            if m["type"] == "status":
                break
    assert any("已中断" in m["payload"].get("text", "") for m in got if m["type"] == "final"), got

    assert got[-1]["payload"]["status"] == "active", got[-1]
    snap = client.get(f"/api/session/{sid}").json()
    assert snap["session_status"] == "active" and snap["card"] is None and snap["mfa"] is None
    again = client.post("/api/confirm", json={"session_id": sid,
                                              "action_id": card["action_id"], "approved": True}).json()
    codes = {m["payload"].get("code") for m in again["messages"] if m["type"] == "error"}
    assert codes & {"ACTION_ALREADY_HANDLED", "ACTION_NOT_FOUND"}, codes


def test_thread_id_survives_manager_restart(client):
    """进程重启后 turn 计数归零：thread_id 含本轮 uuid，避免撞历史 checkpoint 造成消息重放。

    回归：旧实现 `thread_id = session_id:turn` 重启后与首轮同名，
    checkpointer 的 emitted 残留被重新读出（IM/WS 出现「上轮回执 + 本轮确认卡」混排）。
    新 SessionManager 等价进程重启（会话状态/turn 全丢），在 app 同一事件循环内驱动。
    """
    from app.session.manager import SessionManager

    sid = "restart_t1"
    _chat(client, sid, "给赵敏转 200")            # 首轮：留 checkpoint + 待确认卡
    _chat(client, sid, "1")                       # 确认落库，该 thread 已收尾

    fresh = SessionManager()
    out = client.portal.call(fresh.handle_message, sid, "我的余额")
    kinds = [m["type"] for m in out["messages"]]
    assert "receipt" not in kinds and "confirm_card" not in kinds, kinds
    assert "final" in kinds, kinds

