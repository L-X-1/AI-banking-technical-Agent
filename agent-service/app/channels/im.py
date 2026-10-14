"""IM 渠道适配器（doc 02 §10.2 / doc 03 §1.1）：外部 IM 文本归一化为 user_message；
下行消息降级为非流式整段文本（确认卡→“回复 1 确认 / 2 取消”，MFA→短信码文本输入）。

安全不变量：同一 Agent、同一 trace、同一权限裁决/MFA 链路——UI 降级但安全不降级。
"""
import re

# IM 文本指令（doc 04 §4.18）：确认卡选择 / MFA 短信码直输 / 审批链接
CONFIRM_RE = re.compile(r"^\s*([12])\s*$")
MFA_CODE_RE = re.compile(r"^\s*(\d{6})\s*$")


def normalize_inbound(raw: dict) -> dict:
    """外部 IM webhook 原始消息 → 内部上行（user_message/action_confirm/mfa_submit 三选一）。"""
    text = str(raw.get("text") or "").strip()
    if not text:
        return {"type": "unknown", "raw": raw}
    cmd = str(raw.get("command") or "").strip().lower()
    if cmd in ("confirm", "cancel") or (not cmd and CONFIRM_RE.fullmatch(text)):
        digit = "1" if cmd == "confirm" else ("2" if cmd == "cancel" else CONFIRM_RE.fullmatch(text).group(1))
        return {"type": "action_confirm", "approved": digit == "1", "text": text}
    if cmd == "mfa" or MFA_CODE_RE.fullmatch(text):
        code = MFA_CODE_RE.fullmatch(text).group(1) if MFA_CODE_RE.fullmatch(text) else ""
        return {"type": "mfa_submit", "code": code, "text": text}
    return {"type": "user_message", "text": text}


def render_outbound(message: dict) -> str:
    """单条下行消息 → IM 整段文本（非流式；金额/卡号/倒计时原样取自服务端 payload）。"""
    kind = message.get("type")
    p = message.get("payload") or {}
    if kind == "confirm_card":
        rows = "\n".join(f"· {d.get('label')}：{d.get('value')}" for d in (p.get("detail") or []))
        level = "红色高危" if p.get("risk_level") == "red" else "黄色操作"
        reasons = f"\n依据：{'；'.join(p.get('upgrade_reasons') or [])}" if p.get("upgrade_reasons") else ""
        return (f"【需确认·{level}】{p.get('title', '需要您的确认')}\n{rows}\n"
                f"后果：{p.get('consequence', '')}{reasons}\n回复 1 确认 / 2 取消")
    if kind == "mfa_request":
        return (f"【短信验证】验证码已发至 {p.get('target_masked', '')}，"
                f"请直接回复 6 位数字（剩余尝试 {p.get('attempts_left', '')} 次）。")
    if kind == "mfa_sms":
        return str(p.get("content", ""))
    if kind == "clarify_options":
        opts = "\n".join(f"{i + 1}. {o.get('primary', '')}（{o.get('secondary', '')}）"
                         for i, o in enumerate(p.get("options") or []))
        return f"【请选择】{p.get('question', '')}\n{opts}\n回复序号/尾号/备注即可"
    if kind == "receipt":
        detail = " · ".join(str(x.get("value")) for x in (p.get("detail") or []))
        return f"【回执】{p.get('title', '')}｜{p.get('counterparty') or ''}｜{detail}"
    if kind == "notify":
        return f"【通知】{p.get('title', '')}\n{p.get('content', '')}"
    if kind == "error":
        return f"【失败】{p.get('message', '')}（{p.get('code', '')}）"
    if kind == "final":
        return str(p.get("text", ""))
    if kind == "status":
        return ""
    # tool_progress / stream_token 等过程事件：IM 非流式降级通道不转述中间过程（doc 04 §4.18 仅文本+审批）
    if kind in ("tool_progress", "stream_token", "session_ready", "session_snapshot", "mfa_retry"):
        return ""
    return str((p.get("result_summary") or p.get("text") or "").strip())


def render_batch(messages: list[dict]) -> list[str]:
    """一批下行消息 → IM 文本段列表（空段丢弃，保持服务端顺序）。"""
    return [t for t in (render_outbound(m) for m in messages) if t]


def resolve_action_id(session_actions: list[dict]) -> str | None:
    """IM「1/2」无 action_id：取本会话最近一条 pending 确认（服务端校验归属/过期，见 manager）。"""
    pendings = [a for a in session_actions if a.get("status") == "pending"]
    return pendings[-1]["action_id"] if pendings else None
