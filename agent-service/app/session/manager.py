"""会话网关（doc 03 §1.1/§2.1）：状态机 + 图调用/恢复 + 消歧回填 + MFA 校验；M1 为内存版。"""
import time
import uuid
from dataclasses import dataclass, field

from langgraph.types import Command

from ..config import DEMO_USER_ID, MFA_MAX_ATTEMPTS
from ..graph.agent_graph import MFA_CHALLENGES, PENDING_ACTIONS, get_graph
from ..security.breaker import breaker


@dataclass
class Session:
    id: str
    user_id: str = DEMO_USER_ID
    channel: str = "web"
    status: str = "active"          # active/processing/waiting_confirm/waiting_mfa/waiting_clarify
    trace_id: str = ""
    thread_id: str = ""
    turn: int = 0
    last_options: list[dict] = field(default_factory=list)
    pending_intent: dict | None = None
    history: list[dict] = field(default_factory=list)   # 近 8 轮 {text, scenario, slots}（意图指代消解，doc 03 §3.2）


def _msg(kind: str, payload: dict, trace_id: str = "") -> dict:
    m = {"type": kind, "payload": payload}
    if trace_id:
        m["trace_id"] = trace_id
    return m


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    def get(self, session_id: str, channel: str = "web") -> Session:
        if session_id not in self.sessions:
            self.sessions[session_id] = Session(id=session_id, channel=channel)
        return self.sessions[session_id]

    # ── 上行 1/4：user_message ─────────────────────────────
    async def handle_message(self, session_id: str, text: str, channel: str = "web") -> dict:
        s = self.get(session_id, channel)
        s.turn += 1
        resolved_id = resolved_name = prev_slots = None
        if s.status == "waiting_clarify" and s.last_options:
            pick = self._pick_option(s.last_options, text)
            if pick is not None:
                resolved_id = pick["id"]
                resolved_name = pick["primary"].split(" · ")[0]
                prev_slots = (s.pending_intent or {}).get("slots")
                s.last_options = []
                s.pending_intent = None
        s.status = "processing"
        s.trace_id = f"tr_{uuid.uuid4().hex[:8]}"
        # 每轮独立图线程；thread_id 必须含本轮 uuid——进程重启后 turn 计数归零，
        # 若仅用 session_id:turn 会撞上历史 checkpoint 的旧状态（emitted 残留导致消息重放）。
        s.thread_id = f"{s.id}:{s.trace_id}"
        state = dict(session_id=s.id, user_id=s.user_id, trace_id=s.trace_id, user_text=text,
                     node_results={}, emitted=[], decision_log=[],
                     resolved_contact_id=resolved_id, resolved_contact_name=resolved_name,
                     prev_slots=prev_slots, history=list(s.history))
        cfg = {"configurable": {"thread_id": s.thread_id}}
        result = await get_graph().ainvoke(state, cfg)
        self._record_history(s, text, result)
        return self._finish(s, result)

    @staticmethod
    def _record_history(s: Session, text: str, result: dict) -> None:
        """沉淀本轮意图（chat 除外）供后续指代消解，如「再给她转一次」（M3#7 的会话侧基础）。"""
        intent = result.get("intent") or {}
        if not intent.get("scenario") or intent["scenario"] == "chat":
            return
        entry = {"text": text, "scenario": intent["scenario"],
                 "slots": {k: v for k, v in (intent.get("slots") or {}).items()
                           if k not in ("old_password", "new_password")}}   # 口令不落历史
        s.history = (s.history + [entry])[-8:]

    # ── 上行 2/4：action_confirm ───────────────────────────
    # ── 会话快照（doc 04 §7）：刷新/断线重连后原样恢复待办确认卡与 MFA ──
    def snapshot(self, session_id: str) -> dict:
        """状态机镜像 + 待办卡片/MFA（中断时服务端渲染快照，金额/收款人唯一事实源）。"""
        s = self.get(session_id)
        cards = [a for a in PENDING_ACTIONS.values()
                 if a["session_id"] == s.id and a["status"] == "pending" and a.get("card")]
        mfa_rows = [c for c in MFA_CHALLENGES.values()
                    if c["session_id"] == s.id and c["status"] == "pending"]
        card = None
        if cards:
            a = cards[-1]
            card = dict(a["card"])
            card["expires_in_sec"] = max(0, int(a["expires_at"] - time.time()))  # 倒计时双轨：服务端权威
        mfa = None
        if mfa_rows:
            ch = mfa_rows[-1]
            mfa = dict(challenge_id=ch["challenge_id"], type="sms", target_masked="138****6688",
                       expires_in_sec=max(0, int(ch["expires_at"] - time.time())),
                       attempts_left=max(0, MFA_MAX_ATTEMPTS - int(ch.get("attempts") or 0)),
                       code=ch["code"])   # 演示环境直显（MockSmsPanel 同源；真实环境不下发）
        return {"session_id": s.id, "session_status": s.status, "trace_id": s.trace_id,
                "card": card, "mfa": mfa}

    # ── 上行 4/4：interrupt（doc 03 §1.1；doc 06 §3.5 规则 1：Esc 中断全会话生效）──
    async def handle_interrupt(self, session_id: str, mode: str = "stop") -> dict:
        """中断当前待办：关闭本会话遗留 pending（后续步骤不执行），会话回 active。

        被中断的图线程不再 resume（每轮新 thread_id），下一轮输入走全新规划。
        """
        s = self.get(session_id)
        closed = 0
        for k, a in list(PENDING_ACTIONS.items()):
            if a["session_id"] == s.id and a["status"] == "pending":
                PENDING_ACTIONS.patch(k, status="aborted")
                closed += 1
        for k, c in list(MFA_CHALLENGES.items()):
            if c["session_id"] == s.id and c["status"] == "pending":
                MFA_CHALLENGES.patch(k, status="consumed")
                closed += 1
        s.status = "active"
        text = ("已中断本次操作（未执行的步骤已取消）。" if closed
                else "当前没有进行中的操作。")
        return {"session_id": s.id, "trace_id": s.trace_id, "status": "done",
                "session_status": "active", "messages": [_msg("final", {"text": text})]}

    async def handle_confirm(self, session_id: str, action_id: str, approved: bool) -> dict:
        s = self.get(session_id)
        action = PENDING_ACTIONS.get(action_id)
        err = self._validate_action(s, action)
        if err is not None:
            return {"status": s.status, "session_status": s.status, "messages": [_msg("error", err)]}
        result = await get_graph().ainvoke(Command(resume={"approved": bool(approved)}),
                                           {"configurable": {"thread_id": s.thread_id}})
        return self._finish(s, result)

    # ── 上行 3/4：mfa_submit ───────────────────────────────
    async def handle_mfa(self, session_id: str, challenge_id: str, code: str) -> dict:
        s = self.get(session_id)
        st = breaker.status(s.id)                       # 熔断 T2：锁定优先（倒计时内拒绝一切提交）
        if st["locked"]:
            return {"status": s.status, "session_status": s.status,
                    "messages": [_msg("error", {"code": "SESSION_LOCKED",
                                                "message": st["reason"],
                                                "seconds_left": st["seconds_left"]})]}
        ch = MFA_CHALLENGES.get(challenge_id)
        if ch is None or ch["session_id"] != s.id or ch["status"] != "pending":
            return {"status": s.status, "session_status": s.status,
                    "messages": [_msg("error", {"code": "MFA_INVALID", "message": "验证请求不存在或已失效"})]}
        if ch["code"] != (code or "").strip():
            attempts = ch["attempts"] + 1
            left = MFA_MAX_ATTEMPTS - attempts
            row = breaker.record(s.id, "mfa_fail")      # 熔断 T2：连败计数（成功即清零）
            locked = row["state"] == "open" and row["scope"] == "session"
            if left > 0 and not locked:
                MFA_CHALLENGES.patch(challenge_id, attempts=attempts)
                return {"status": s.status, "session_status": s.status, "messages": [
                    _msg("error", {"code": "MFA_MISMATCH", "message": f"验证码错误，剩余 {left} 次"}),
                    _msg("mfa_retry", {"challenge_id": challenge_id, "attempts_left": left})]}
            MFA_CHALLENGES.patch(challenge_id, attempts=attempts,
                                 status="failed" if left <= 0 else "pending")
            result = await get_graph().ainvoke(Command(resume={"mfa_passed": False}),
                                               {"configurable": {"thread_id": s.thread_id}})
            out = self._finish(s, result)
            if locked:                                   # 3 次失败 → 锁定 15 分钟（doc 05 M2#3）
                out["messages"].append(_msg("error", {
                    "code": "SESSION_LOCKED", "message": row["reason"],
                    "seconds_left": max(0, int(row["expires_at"] - time.time()))}))
            return out
        MFA_CHALLENGES.patch(challenge_id, status="passed")
        breaker.record(s.id, "mfa_ok")                   # 验证通过 → 连败计数清零
        result = await get_graph().ainvoke(Command(resume={"mfa_passed": True}),
                                           {"configurable": {"thread_id": s.thread_id}})
        return self._finish(s, result)

    # ── 内部：结果收集与状态机镜像 ──────────────────────────
    def _finish(self, s: Session, result: dict) -> dict:
        messages = list(result.get("emitted") or [])
        for it in (result.get("__interrupt__") or []):   # interrupt 值 → 前端可推送消息
            val = getattr(it, "value", None) or {}
            if isinstance(val, dict) and val.get("type"):
                messages.append(_msg(val["type"], val.get("payload") or {}, s.trace_id))
        status = result.get("status") or "done"
        if result.get("clarify"):
            s.last_options = result["clarify"].get("options", [])
            s.pending_intent = result.get("intent")
            s.status = "waiting_clarify"
        if status in ("done", "aborted", "rejected"):   # 终态清理：关闭本会话遗留的 pending 登记（写回 SQLite）
            for k, c in list(MFA_CHALLENGES.items()):
                if c["session_id"] == s.id and c["status"] == "pending":
                    MFA_CHALLENGES.patch(k, status="consumed")
            for k, a in list(PENDING_ACTIONS.items()):
                if a["session_id"] == s.id and a["status"] == "pending":
                    PENDING_ACTIONS.patch(k, status="succeeded" if status == "done" else "aborted")
        pending = [a for a in PENDING_ACTIONS.values() if a["session_id"] == s.id and a["status"] == "pending"]
        mfa = [c for c in MFA_CHALLENGES.values() if c["session_id"] == s.id and c["status"] == "pending"]
        if mfa:
            s.status = "waiting_mfa"
            ch = mfa[-1]
            messages.append(_msg("mfa_sms", {"content": f"【智银】验证码 {ch['code']}，5 分钟内有效。",
                                             "challenge_id": ch["challenge_id"]}))
        elif pending:
            s.status = "waiting_confirm"
        elif status in ("done", "aborted", "rejected"):
            s.status = "active"
            s.last_options = []
        return {"session_id": s.id, "trace_id": s.trace_id, "status": status,
                "session_status": s.status, "messages": messages}

    def _validate_action(self, s: Session, action: dict | None) -> dict | None:
        st = breaker.status(s.id)                       # 熔断：session 锁定优先（确认入口同样受限）
        if st["locked"]:
            return {"code": "SESSION_LOCKED", "message": st["reason"],
                    "seconds_left": st["seconds_left"]}
        if action is None or action["session_id"] != s.id:
            return {"code": "ACTION_NOT_FOUND", "message": "该确认请求不存在或不属于本会话"}
        if action["status"] != "pending":
            return {"code": "ACTION_ALREADY_HANDLED", "message": f"该操作已处于 {action['status']} 状态"}
        if time.time() > action["expires_at"]:
            PENDING_ACTIONS.patch(action["action_id"], status="expired")
            return {"code": "ACTION_EXPIRED", "message": "确认已超时（5 分钟），本次操作已自动取消"}
        return None

    @staticmethod
    def _pick_option(options: list[dict], text: str) -> dict | None:
        digits = "".join(ch for ch in text if ch.isdigit())
        for opt in options:
            if digits and digits in opt["primary"]:
                return opt
        for opt in options:
            if opt.get("secondary") and opt["secondary"] in text:
                return opt
        for opt in options:
            name = opt["primary"].split(" · ")[0]
            if name and name in text:
                return opt
        return None


manager = SessionManager()
