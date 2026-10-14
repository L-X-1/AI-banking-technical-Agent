"""agent-service FastAPI 入口：REST + WebSocket(/ws/web) + 审计回放 + 极简演示页 + 银行侧通知回调（doc 03 §6.1）。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import DEMO_USER_ID
from .graph.agent_graph import get_graph, init_checkpointer
from .security.audit import audit
from .session.manager import manager

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# 在线 WS 连接注册表：user_id → 连接集合（演示单用户；生产按 JWT 归属）
WS_HUB: dict[str, set[WebSocket]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_checkpointer()   # M2：SqliteSaver 检查点（doc 03 §7.1，异步版）
    get_graph()   # 预热编译
    yield


app = FastAPI(title="agent-service", version="0.1.0", lifespan=lifespan)


class ChatIn(BaseModel):
    session_id: str
    text: str
    channel: str = "web"


class ConfirmIn(BaseModel):
    session_id: str
    action_id: str
    approved: bool


class MfaIn(BaseModel):
    session_id: str
    challenge_id: str
    code: str


class NotifyIn(BaseModel):
    """银行侧事件回调契约（doc 03 §6.2）：任务触发/下单成功/提醒/失败。"""
    user_id: str
    event_type: str
    title: str
    content: str
    trace_id: str = ""


class ImIn(BaseModel):
    """模拟 IM webhook 上行（doc 02 §10.2 / doc 04 §4.18）：纯文本 + 可选显式命令。"""
    session_id: str
    text: str = ""
    command: str = ""   # confirm | cancel | mfa | ""（空则按文本 1/2/6 位码归一化）


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agent-service"}


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict:
    return await manager.handle_message(body.session_id, body.text, body.channel)


@app.post("/api/confirm")
async def confirm(body: ConfirmIn) -> dict:
    return await manager.handle_confirm(body.session_id, body.action_id, body.approved)


@app.post("/api/mfa")
async def mfa(body: MfaIn) -> dict:
    return await manager.handle_mfa(body.session_id, body.challenge_id, body.code)


@app.get("/api/audit/{trace_id}")
def get_audit(trace_id: str) -> dict:
    events = audit.fetch(trace_id)
    return {"trace_id": trace_id, "events": events, "kinds": sorted({e["node"] for e in events})}


@app.post("/api/internal/notify")
async def internal_notify(body: NotifyIn) -> dict:
    """接收 bank-core 调度器事件 → 推送用户在线渠道（doc 03 §6.2；离线则丢弃，演示环境免存储）。"""
    msg = {"type": "notify",
           "payload": {"event_type": body.event_type, "title": body.title, "content": body.content}}
    if body.trace_id:
        msg["trace_id"] = body.trace_id
    delivered = 0
    for ws in list(WS_HUB.get(body.user_id, set())):
        try:
            await ws.send_json(msg)
            delivered += 1
        except Exception:  # noqa: BLE001  断连清理
            WS_HUB.get(body.user_id, set()).discard(ws)
    return {"code": "OK", "delivered": delivered}


@app.post("/api/im/webhook")
async def im_webhook(body: ImIn) -> dict:
    """模拟 IM webhook（doc 02 §10.2 / M3#8）：归一化上行 → 同一 manager/同一 trace →
    下行整段文本（channels.im 渲染，非流式）。"""
    from .channels.im import normalize_inbound, render_batch, resolve_action_id
    from .session.store import MFA_CHALLENGES, PENDING_ACTIONS

    up = normalize_inbound({"text": body.text, "command": body.command})
    session_id = body.session_id or "s_im"
    if up["type"] == "action_confirm":
        action_id = resolve_action_id(
            [a for a in PENDING_ACTIONS.values() if a.get("session_id") == session_id])
        if not action_id:
            return {"session_id": session_id, "session_status": manager.get(session_id).status,
                    "replies": ["【失败】当前没有待确认的操作（ACTION_NOT_FOUND）"]}
        out = await manager.handle_confirm(session_id, action_id, up["approved"])
    elif up["type"] == "mfa_submit":
        pendings = [c for c in MFA_CHALLENGES.values()
                    if c.get("session_id") == session_id and c.get("status") == "pending"]
        if not pendings or not up.get("code"):
            return {"session_id": session_id, "session_status": manager.get(session_id).status,
                    "replies": ["【短信验证】请直接回复 6 位数字验证码。"]}
        ch = pendings[-1]
        out = await manager.handle_mfa(session_id, ch["challenge_id"], up["code"])
    elif up["type"] == "user_message":
        out = await manager.handle_message(session_id, up["text"], channel="im")
    else:
        return {"session_id": session_id, "session_status": "active", "replies": []}
    return {"session_id": out.get("session_id", session_id), "trace_id": out.get("trace_id", ""),
            "session_status": out.get("session_status", "active"),
            "replies": render_batch(out.get("messages") or [])}


@app.get("/im", include_in_schema=False)
def im_page() -> FileResponse:
    """M3#8 模拟 IM 页面（doc 04 §4.18：390px 手机卡片，文本 + 审批链接 + 短信码直输）。"""
    return FileResponse(os.path.join(STATIC_DIR, "im.html"))


@app.get("/api/session/{session_id}")
def get_session_snapshot(session_id: str) -> dict:
    """会话快照（doc 04 §7）：刷新/断线重连后恢复状态机与待办卡片/MFA。"""
    return manager.snapshot(session_id)


@app.get("/demo")
def demo_page() -> FileResponse:
    """M1#9 极简聊天页（渲染确认卡 / MFA / 回执；样式从简，风格改版在 M4）。"""
    return FileResponse(os.path.join(STATIC_DIR, "demo.html"))


@app.websocket("/ws/web")
async def ws_web(ws: WebSocket) -> None:
    await ws.accept()
    WS_HUB.setdefault(DEMO_USER_ID, set()).add(ws)   # 演示单用户；通知推送的在线判定依据
    session_id = ws.query_params.get("session") or "s_demo"
    await ws.send_json({"type": "session_ready", "payload": {"session_id": session_id}})
    snap = manager.snapshot(session_id)       # doc 04 §7：重连/刷新恢复待办块（黄卡/MFA）
    if snap.get("card") or snap.get("mfa"):
        await ws.send_json({"type": "session_snapshot", "payload": snap})
    try:
        while True:
            msg = await ws.receive_json()
            kind = msg.get("type")
            if kind == "user_message":
                out = await manager.handle_message(session_id, msg.get("text", ""))
            elif kind == "action_confirm":
                out = await manager.handle_confirm(session_id, msg.get("action_id", ""), bool(msg.get("approved")))
            elif kind == "mfa_submit":
                out = await manager.handle_mfa(session_id, msg.get("challenge_id", ""), msg.get("code", ""))
            elif kind == "interrupt":
                out = await manager.handle_interrupt(session_id, msg.get("mode", "stop"))
            else:
                out = {"messages": [{"type": "error", "payload": {"code": "BAD_MESSAGE",
                                                                  "message": f"未知消息类型 {kind}"}}],
                       "session_status": "active"}
            for m in out.get("messages", []):
                await ws.send_json(m)
            await ws.send_json({"type": "status", "payload": {"status": out.get("session_status", "active")}})
    except WebSocketDisconnect:
        pass
    finally:
        WS_HUB.get(DEMO_USER_ID, set()).discard(ws)
