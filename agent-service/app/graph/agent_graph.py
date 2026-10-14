"""LangGraph 图（doc 02 §6/§7）：guard_in → intent → planner → executor → tool_dispatch → reflector → responder。

M3 Step 2：LLM 意图/规划/回复编排（doc 03 §3）——三节点先走 LLM（OpenAI 兼容端点，
prompts/*.md 为唯一提示词来源），JSON 校验失败/超时/无密钥 → 回退规则版（接口不变）；
LLM 规划产出 DAG 经 validate_dag 校验（工具存在/无环/引用合法），risk 一律由服务端
注册表重盖章（doc 02 §8.3 铁律）；回复阶段工具结果以 wrap_untrusted() 包裹后才进入
LLM 上下文（doc 02 §9.1 数据隔离）。
M2 安全加固：注入双路检测（security/injection.py，规则+模型）→ 回复幻觉校验（verifier，重生成≤2→保守话术）
→ 熔断四触发（breaker，locked 优先）→ SqliteSaver checkpointer（doc 03 §7.1）
→ pending_actions/mfa_challenges → SQLite（doc 02 §3.2）。M1 基线：转账/余额全链路 + 审计六类事件。
"""
import calendar
import hashlib
import re
from datetime import date, datetime, timedelta
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.types import interrupt

from ..config import AGENT_DB_PATH
from ..llm import chat as llm_chat
from ..llm import extract_json, llm_enabled, load_prompt, render_prompt
from ..security import audit as audit_mod
from ..security.breaker import breaker
from ..security.injection import detector, wrap_untrusted
from ..security.permission import decide
from ..security.verifier import CONSERVATIVE_REPLY, verifier
from ..session.store import MFA_CHALLENGES, PENDING_ACTIONS   # doc 02 §3.2 SQLite 持久化
from ..tools.bank_client import BankClient
from ..tools.executor import run_tool, today_transfer_total
from ..tools.specs import TOOL_SPECS, spec

TRANSFER_RE = re.compile(
    r"给\s*(?P<name>[\u4e00-\u9fa5A-Za-z\-]{1,12}?)\s*转\s*(?P<amount>\d+(?:\.\d+)?)\s*元?"
    r"(?:\s*[，,]\s*备注\s*(?P<remark>[\u4e00-\u9fa5A-Za-z0-9 ]{1,20}))?")
BALANCE_RE = re.compile(r"(余额|还有多少钱|多少钱)")
PRONOUN_RE = re.compile(r"(她|他|它|这边|那边|刚才|上次|同样|同样地|同一个人|同一人|继续|接着|再来|还有|另外)")
TRANSFER_VERB_RE = re.compile(r"(转|汇|付|给|打)(.{0,6})(一|另|再|又|还|继续|接着)?(笔|次|下|回|个)?")
AMOUNT_NOREMARK_RE = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s*元?\s*(?:再|又|还)?\s*(?:转|汇|付|给|打)?\s*(?:她|他|它|这边|那边|刚才|那里)?")
AA_RE = re.compile(r"AA|aa")
AA_MEMBERS_RE = re.compile(r"(?:我们|咱俩|我们俩|我们仨|我们三个|(?P<n>\d+)\s*(?:个)?人)")

# ── M3 Step 2：规则意图补充（LLM 不可用时的降级路；六场景全覆盖，doc 06 §6.3）──
BILLING_RE = re.compile(r"(账单|花了多少|消费|开销|支出|花钱|花哪了)")
ANOMALY_RE = re.compile(r"(异常|可疑|奇怪|不对劲)")
REPORT_RE = re.compile(r"(报告|总结|汇总|月报|分析)")
WEALTH_RE = re.compile(r"(理财|年化|收益|申购|赎回|持仓|攒点钱|买.{0,12}(?:万|元|块|块钱))")
SUB_RE = re.compile(r"(订阅|续费|自动扣费|扣费服务|取消.{0,8}扣费)")
CARD_RE = re.compile(r"(虚拟卡|挂失|解挂|冻结.{0,4}卡|卡.{0,4}冻结|解冻.{0,4}卡|卡.{0,4}解冻|卡片?额度|调.{0,2}额度)")
CROSS_RE = re.compile(r"(生日|纪念日|提醒我|到时候提醒|每个月|每月|定时)")
PASSWORD_RE = re.compile(r"(?:修改|更换|更改|改).{0,8}密码|密码.{0,12}(?:改成|改为|换成|改)")
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|千)?\s*(?:元|块|块钱)?")
TAIL_RE = re.compile(r"尾号\s*(\d{4})|(\d{4})\s*(?:的)?(?:卡|卡片)")

SCENARIOS = {"transfer", "aa_split", "query_balance", "billing", "wealth",
             "subscription", "card", "cross_scenario", "change_password", "chat", "other"}


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: str
    trace_id: str
    user_text: str
    intent: dict | None
    dag: dict | None
    current_node_id: str | None
    node_results: dict[str, Any]
    pending_action: dict | None
    security_flags: dict
    emitted: Annotated[list[dict], add]      # 待推送前端的消息
    clarify: dict | None
    resolved_contact_id: str | None
    resolved_contact_name: str | None
    prev_slots: dict | None                  # 消歧回填时携带上一轮槽位（金额/备注）
    history: list[dict]                      # 会话近 8 轮 {text, scenario, slots}（意图指代消解，doc 03 §3.2 规则 2）
    final_reply: str | None
    status: str                              # running/waiting_confirm/waiting_mfa/waiting_clarify/done/aborted/rejected
    decision_log: Annotated[list[dict], add]


def _stable_code(seed: str) -> str:
    """演示 MFA 验证码：确定性生成（节点重放安全，MockSmsPanel 直显）。"""
    return f"{int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 1000000:06d}"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _latest_transfer_slots(history: list[dict]) -> dict | None:
    """最近一轮 transfer 槽位（M3#7 指代回填源；contact_id/keyword 任一存在即有效）。"""
    for h in reversed(history or []):
        if h.get("scenario") != "transfer":
            continue
        slots = h.get("slots") or {}
        if slots.get("contact_id") or slots.get("keyword"):
            return dict(slots)
    return None


def _rule_pronoun_refill(text: str, state: AgentState) -> dict | None:
    """规则路代词/省略回填（M3#7，LLM 不可用时确定性兜底，doc 03 §3.2 规则 2）。

    仅处理 transfer/aa_split；回填只读 history 中最近一轮 transfer 的 slots，
    contact_id/keyword/amount/remark 均来自服务端已裁决/已返回的旧值，不做任何推断。
    """
    prev = _latest_transfer_slots(state.get("history") or [])
    if not prev:
        return None
    explicit = TRANSFER_RE.search(text)
    if explicit and not re.search(r"(她|他|它)", text):
        return None   # 无代词的显式转账：走原有分支（保持 keyword 精确）
    if explicit and re.search(r"(她|他|它)", text):
        # 「再给她转 300」：收款人=代词→历史回填；金额=本轮显式数字（覆盖上一笔）。
        amount_m = AMOUNT_NOREMARK_RE.search(text)
        slots = dict(contact_id=prev.get("contact_id"), keyword=prev.get("keyword"),
                     amount=float(amount_m.group("amount")) if amount_m else prev.get("amount", 0.0),
                     remark=(explicit.group("remark") or "").strip() or prev.get("remark") or "")
        return dict(scenario="transfer", confidence=0.9, ambiguous=False, slots=slots)
    if not PRONOUN_RE.search(text):
        return None
    if not TRANSFER_VERB_RE.search(text):
        return None
    slots = dict(contact_id=prev.get("contact_id"), keyword=prev.get("keyword"),
                 amount=prev.get("amount", 0.0), remark=prev.get("remark") or "")
    amount_m = AMOUNT_NOREMARK_RE.search(text)
    if amount_m:
        slots["amount"] = float(amount_m.group("amount"))
    if not slots.get("contact_id") and not slots.get("keyword"):
        return dict(scenario="transfer", confidence=0.65, ambiguous=True, slots={},
                    question="刚才那笔是转给谁、转多少？我按上一笔帮你补上。")
    return dict(scenario="transfer", confidence=0.88, ambiguous=False, slots=slots)


def parse_intent(text: str, state: AgentState) -> dict:
    """规则版意图识别（M1；M3 换 LLM 结构化输出，接口不变）。"""
    pre = state.get("resolved_contact_id")
    if pre:
        prev = state.get("prev_slots") or (state.get("intent") or {}).get("slots", {})
        m = TRANSFER_RE.search(text) or TRANSFER_RE.search(state.get("user_text", ""))
        amount = float(m.group("amount")) if m else float(prev.get("amount") or 0)
        remark = ((m.group("remark") or "").strip() if m else "") or prev.get("remark") or ""
        return dict(scenario="transfer", confidence=0.95, ambiguous=False,
                    slots=dict(contact_id=pre, amount=amount, remark=remark))
    refill = _rule_pronoun_refill(text, state)   # M3#7：规则路代词/省略回填（先于显式匹配）
    if refill:
        return refill
    m = TRANSFER_RE.search(text)          # 转账优先于 AA（避免备注里的 "AA" 误判场景）
    if m:
        slots = dict(keyword=m.group("name").strip(), amount=float(m.group("amount")),
                     remark=(m.group("remark") or "").strip())
        mm = re.search(r"每(?:个)?月\s*(\d{1,2})\s*[日号]?", text)   # 周期性转账 → 定时任务（D 联动）
        if mm:
            slots["recurrence"] = "monthly"
            slots["schedule_time"] = _next_monthly(int(mm.group(1)))
        return dict(scenario="transfer", confidence=0.92, ambiguous=False, slots=slots)
    if AA_RE.search(text):
        n = 2
        mm = AA_MEMBERS_RE.search(text)
        if mm and mm.group("n"):
            n = max(1, int(mm.group("n")) - 1)
        amt = re.search(r"(\d+(?:\.\d+)?)", text)
        return dict(scenario="aa_split", confidence=0.9, ambiguous=False,
                    slots=dict(total_amount=float(amt.group(1)) if amt else 0.0, member_count=n, remark="AA 拆分"))
    m3 = _rule_m3_intent(text)             # M3 六场景规则降级路（doc 03 §10 提示词不可用 → 规则回退）
    if m3:
        return m3
    if BALANCE_RE.search(text):
        return dict(scenario="query_balance", confidence=0.95, ambiguous=False, slots={})
    return dict(scenario="chat", confidence=0.3, ambiguous=True, slots={},
                question="我能办理转账、AA 收款、账单分析、理财、订阅管理、卡片管理和定时联动，换个说法试试？")


# ── 规则意图：M3 六场景辅助解析（金额/账期/尾号/日期/名称的确定性提取）──
def _split_amount(text: str) -> tuple[float, str]:
    """提取首个金额（支持 万/千 单位）并从原文摘除，返回 (金额, 剩余文本)。"""
    m = AMOUNT_RE.search(text)
    if not m:
        return 0.0, text
    factor = {"万": 10000, "千": 1000}.get(m.group(2)) or 1
    return float(m.group(1)) * factor, (text[:m.start()] + text[m.end():])


def _period(text: str) -> str | None:
    """账期归一：上个月/上月 → 上一自然月；本月 → 当月；YYYY-MM 显式；缺省 None（bank-core 默认上月）。"""
    today = date.today()
    if re.search(r"(上个月|上月|上一月)", text):
        prev = today.replace(day=1) - timedelta(days=1)
        return prev.strftime("%Y-%m")
    if re.search(r"(这个月|本月|当月|这月)", text):
        return today.strftime("%Y-%m")
    m = re.search(r"(20\d{2})[-年/.](\d{1,2})", text)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else None


def _tail(text: str) -> str:
    m = TAIL_RE.search(text)
    return (m.group(1) or m.group(2)) if m else ""


def _next_monthly(day: int) -> str:
    """每月 D 号的下一次触发日（今天已过 → 下月；非法日期收敛到月末），09:00 执行。"""
    today = date.today()
    year, month = today.year, today.month
    if today.day >= day:
        month += 1
    if month > 12:
        year, month = year + 1, 1
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{min(day, last):02d} 09:00"


def _cross_slots(text: str) -> dict:
    """跨场景（生日联动/定时提醒）槽位：日期/预算/锁额/对象/礼品清单（doc 06 §6.3 场景 D）。"""
    today = date.today()
    slots: dict = {"occasion": "生日" if "生日" in text else ("纪念日" if "纪念日" in text else "提醒")}
    m = re.search(r"下(?:个)?月\s*(\d{1,2})\s*[日号]", text)
    if m:
        month = today.month % 12 + 1
        year = today.year + (1 if today.month == 12 else 0)
        day = int(m.group(1))
    else:
        m2 = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
        if m2:
            month, day = int(m2.group(1)), int(m2.group(2))
            year = today.year + (1 if (month, day) <= (today.month, today.day) else 0)
        elif "明天" in text or "后天" in text:
            d = today + timedelta(days=2 if "后天" in text else 1)
            slots["date"] = d.isoformat()
            slots["time_hint"] = ("下午" if "下午" in text else
                                  "晚上" if "晚上" in text else "上午" if "上午" in text else "")
            return _cross_common(text, slots)
        else:
            return slots
    try:
        slots["date"] = date(year, month, day).isoformat()
    except ValueError:
        return slots
    return _cross_common(text, slots)


def _cross_common(text: str, slots: dict) -> dict:
    m = re.search(r"预算\s*(\d+(?:\.\d+)?)", text)
    if m:
        slots["budget"] = float(m.group(1))
    m = re.search(r"(?:锁定|冻结|锁)\s*(\d+(?:\.\d+)?)\s*(?:元|块)?", text)
    if m:
        slots["lock_amount"] = float(m.group(1))
    m = re.search(r"(爱人|老婆|妻子|老公|丈夫|妈妈|爸爸|女友|男友|女朋友|男朋友)", text)
    if m:
        slots["recipient"] = m.group(1)
    items = [w for w in ("鲜花", "蛋糕", "礼物", "巧克力") if w in text]
    if items:
        slots["items"] = items
    return slots


def _rule_m3_intent(text: str) -> dict | None:
    """M3 六场景规则意图（transfer/aa/balance 之外）。命中返回 intent，未命中 None。"""
    if PASSWORD_RE.search(text):
        toks = re.findall(r"[A-Za-z0-9]{6,20}", text)
        if len(toks) >= 2:
            return dict(scenario="change_password", confidence=0.85, ambiguous=False,
                        slots={"old_password": toks[0], "new_password": toks[1]})
        return dict(scenario="change_password", confidence=0.6, ambiguous=True, slots={},
                    question="请按「把登录密码从 旧密码 改成 新密码」告诉我（新密码至少 8 位，含字母和数字）。")
    if BILLING_RE.search(text):
        kind = "anomalies" if ANOMALY_RE.search(text) else ("report" if REPORT_RE.search(text) else "category")
        return dict(scenario="billing", confidence=0.88, ambiguous=False,
                    slots={"kind": kind, "period": _period(text)})
    if WEALTH_RE.search(text):
        amt, rest = _split_amount(text)
        name = re.sub(r"(帮我|我要|我想|一?下|了|的|理财|产品|基金|买|申购|购入|投|赎回|卖出)",
                      " ", rest).strip(" ，。,.！!？?")[:20]
        if re.search(r"(赎回|卖出)", text):
            return dict(scenario="wealth", confidence=0.86, ambiguous=False,
                        slots={"action": "redeem", "product_name": name, "amount": amt})
        if re.search(r"(买|申购|购入|投)", text):
            if not name or amt <= 0:
                return dict(scenario="wealth", confidence=0.7, ambiguous=True,
                            slots={"action": "purchase", "product_name": name, "amount": amt},
                            question="想买哪只理财产品、投入多少钱？")
            return dict(scenario="wealth", confidence=0.86, ambiguous=False,
                        slots={"action": "purchase", "product_name": name, "amount": amt})
        if re.search(r"(持仓|持有)", text):
            return dict(scenario="wealth", confidence=0.88, ambiguous=False, slots={"action": "holdings"})
        risk = 2 if "稳健" in text else (1 if "保守" in text else (4 if re.search(r"(进取|积极)", text) else 2))
        return dict(scenario="wealth", confidence=0.86, ambiguous=False,
                    slots={"action": "recommend", "risk_max": risk})
    if SUB_RE.search(text):
        if re.search(r"(取消|退订|关掉|关闭|停掉|停了)", text):
            m = re.search(r"(?:取消|退订|关掉|关闭|停掉|停了)(?:我?的|那个|一下|下)?"
                          r"([\u4e00-\u9fa5A-Za-z0-9· ]{1,20}?)(?:的?(?:订阅|自动续费|扣费|服务)|$)", text)
            merchant = (m.group(1).strip() if m else "")
            if not merchant:
                return dict(scenario="subscription", confidence=0.7, ambiguous=True,
                            slots={"action": "cancel"}, question="想取消哪一个订阅服务？")
            return dict(scenario="subscription", confidence=0.86, ambiguous=False,
                        slots={"action": "cancel", "merchant": merchant})
        return dict(scenario="subscription", confidence=0.88, ambiguous=False, slots={"action": "detect"})
    if CARD_RE.search(text):
        tail = _tail(text)
        if "虚拟卡" in text:
            return dict(scenario="card", confidence=0.88, ambiguous=False, slots={"action": "apply"})
        action = ("report_loss" if "挂失" in text else
                  "cancel_loss" if "解挂" in text else
                  "freeze" if "冻结" in text else
                  "unfreeze" if "解冻" in text else
                  "limit" if "额度" in text else "")
        if not action:
            return dict(scenario="card", confidence=0.6, ambiguous=True, slots={},
                        question="想对卡片做什么？（申请虚拟卡 / 调额度 / 冻结 / 解冻 / 挂失 / 解挂）")
        slots: dict = {"action": action, "card_tail": tail}
        if action == "limit":
            slots["daily_limit"] = _split_amount(text)[0]
        if not tail:
            return dict(scenario="card", confidence=0.72, ambiguous=True, slots=slots,
                        question="要操作哪张卡？告诉我卡号后四位就行。")
        return dict(scenario="card", confidence=0.86, ambiguous=False, slots=slots)
    if CROSS_RE.search(text):
        slots = _cross_slots(text)
        slots["text"] = text
        if not slots.get("date"):
            q = (f"是哪一天的{slots['occasion']}？" if slots.get("occasion") in ("生日", "纪念日")
                 else "什么时候提醒你？（比如：明天下午 / 10 月 1 号）")
            return dict(scenario="cross_scenario", confidence=0.7, ambiguous=True, slots=slots, question=q)
        return dict(scenario="cross_scenario", confidence=0.84, ambiguous=False, slots=slots)
    return None

def _node(nid: str, tool: str, args: dict, depends_on: list[str] | None = None) -> dict:
    """DAG 节点统一构造：risk 永远来自服务端注册表（doc 02 §8.3；LLM 产出亦经 validate_dag 重盖章）。"""
    return dict(id=nid, tool=tool, args=args, depends_on=depends_on or [],
                risk=spec(tool).base_risk)


def plan_dag(intent: dict) -> dict:
    """规则版 DAG 规划（LLM 降级路；doc 02 §7.1）：transfer/aa/balance + M3 六场景静态 DAG。"""
    s = intent["scenario"]
    if s == "transfer":
        slots = intent["slots"]
        if slots.get("recurrence"):  # 每月 D 号 → 定时转账任务（bank-core 调度器执行，doc 06 §6.2）
            return dict(goal=f"每月定时转账 ¥{slots.get('amount')}", nodes=[
                _node("n1", "resolve_contact", dict(keyword=slots.get("keyword", ""))),
                _node("n2", "create_scheduled_task",
                      dict(task_type="transfer", to_contact_id="$n1.contact_id",
                           amount=slots.get("amount"), remark=slots.get("remark", ""),
                           next_run_at=slots.get("schedule_time"), recurrence="monthly"),
                      ["n1"])])
        if slots.get("contact_id"):
            return dict(goal=f"转账 ¥{slots['amount']}", nodes=[
                dict(id="n1", tool="transfer",
                     args=dict(to_contact_id=slots["contact_id"], amount=slots["amount"],
                               remark=slots.get("remark", "")),
                     depends_on=[], risk=spec("transfer").base_risk)])
        return dict(goal=f"给{slots.get('keyword')}转账 ¥{slots.get('amount')}", nodes=[
            dict(id="n1", tool="resolve_contact", args=dict(keyword=slots.get("keyword", "")), depends_on=[],
                 risk=spec("resolve_contact").base_risk),
            dict(id="n2", tool="transfer",
                 args=dict(to_contact_id="$n1.contact_id", amount=slots.get("amount"),
                           remark=slots.get("remark", "")),
                 depends_on=["n1"], risk=spec("transfer").base_risk)])
    if s == "aa_split":
        slots = intent["slots"]
        # 单节点：成员数（人数-1，如「我们仨」→2）与 keyword 由执行器解析为 contact_ids，
        # 不再经 resolve_contact 节点——多候选消歧会把 AA 流程打断（doc 05 M3#5）。
        return dict(goal=f"AA 收款 ¥{slots.get('total_amount')}", nodes=[
            _node("n1", "aa_split", dict(total_amount=slots.get("total_amount"),
                  member_count=slots.get("member_count") or 2,
                  keyword="同事", remark=slots.get("remark", "AA 拆分")))])
    if s == "query_balance":
        return dict(goal="查询账户余额", nodes=[_node("n1", "query_balance", {})])
    if s == "billing":
        slots = intent.get("slots") or {}
        return dict(goal="账单分析", nodes=[_node("n1", "analyze_billing",
                    dict(kind=slots.get("kind") or "category", period=slots.get("period")))])
    if s == "subscription":
        slots = intent.get("slots") or {}
        if slots.get("action") == "cancel" and slots.get("merchant"):
            return dict(goal=f"取消订阅：{slots['merchant']}",
                        nodes=[_node("n1", "cancel_subscription", dict(merchant=slots["merchant"]))])
        return dict(goal="订阅检测", nodes=[_node("n1", "detect_subscriptions", {})])
    if s == "wealth":
        slots = intent.get("slots") or {}
        action = slots.get("action") or "recommend"
        if action == "holdings":
            return dict(goal="查询持仓", nodes=[_node("n1", "query_holdings", {})])
        if action == "purchase":
            args = dict(amount=slots.get("amount") or 0)
            args["product_id" if slots.get("product_id") else "product_name"] = \
                slots.get("product_id") or slots.get("product_name") or ""
            return dict(goal=f"申购理财 ¥{args['amount']}", nodes=[_node("n1", "purchase_wealth", args)])
        if action == "redeem":
            args = dict(amount=slots.get("amount") or 0)
            key = "holding_id" if slots.get("holding_id") else "product_name"
            args[key] = slots.get("holding_id") or slots.get("product_name") or ""
            return dict(goal=f"赎回理财 ¥{args['amount']}", nodes=[_node("n1", "redeem_wealth", args)])
        return dict(goal="理财推荐", nodes=[_node("n1", "recommend_wealth",
                    dict(risk_max=slots.get("risk_max") or 2))])
    if s == "card":
        slots = intent.get("slots") or {}
        action = slots.get("action") or ""
        if action == "apply":
            return dict(goal="申请虚拟卡", nodes=[_node("n1", "apply_virtual_card", {})])
        tool = {"freeze": "freeze_card", "unfreeze": "unfreeze_card",
                "report_loss": "report_card_loss", "cancel_loss": "cancel_card_loss",
                "limit": "adjust_card_limit"}.get(action)
        if tool:
            args: dict = {"card_tail": slots.get("card_tail") or ""}
            if action == "limit":
                args["daily_limit"] = slots.get("daily_limit") or 0
            return dict(goal="卡片管理", nodes=[_node("n1", tool, args)])
        return dict(goal="闲聊兜底", nodes=[])
    if s == "change_password":
        slots = intent.get("slots") or {}
        return dict(goal="修改登录密码", nodes=[_node("n1", "change_password",
                    dict(old_password=slots.get("old_password") or "",
                         new_password=slots.get("new_password") or ""))])
    if s == "cross_scenario":
        slots = intent.get("slots") or {}
        occasion = slots.get("occasion") or "提醒"
        if occasion in ("生日", "纪念日") and slots.get("date"):
            # 生日联动四件套（doc 02 §7.1 示例）：锁资金 → 下单 → 前一日提醒 → 当日解锁
            recipient = slots.get("recipient") or "对方"
            d = date.fromisoformat(slots["date"])
            lock = float(slots.get("lock_amount") or 1000)
            budget = float(slots.get("budget") or 600)
            items = slots.get("items") or ["鲜花", "蛋糕"]
            gift_at = f"{(d - timedelta(days=2)).isoformat()} 09:00"
            remind_at = f"{(d - timedelta(days=1)).isoformat()} 09:00"
            unlock_at = f"{d.isoformat()} 20:00"
            return dict(goal=f"{recipient}{occasion}联动（{slots['date']}）", nodes=[
                _node("n1", "freeze_funds", dict(amount=lock, reason=f"{recipient}{occasion}资金锁定")),
                _node("n2", "place_gift_order", dict(items=items, amount=budget,
                      recipient=recipient, next_run_at=gift_at), ["n1"]),
                _node("n3", "create_scheduled_task",
                      dict(task_type="reminder",
                           text=f"明天是{recipient}的{occasion}，礼品（{'、'.join(items)}）已安排，锁定资金将自动解冻",
                           next_run_at=remind_at), ["n1"]),
                _node("n4", "create_scheduled_task",
                      dict(task_type="fund_unlock", amount=lock, next_run_at=unlock_at), ["n1"])])
        if slots.get("date"):  # 通用提醒（含 明天/后天）
            hour = {"下午": 14, "晚上": 19}.get(slots.get("time_hint") or "", 9)
            return dict(goal="定时提醒", nodes=[_node("n1", "create_scheduled_task",
                        dict(task_type="reminder", text=slots.get("text") or "待办提醒",
                             next_run_at=f"{slots['date']} {hour:02d}:00"))])
        return dict(goal="闲聊兜底", nodes=[])
    return dict(goal="闲聊兜底", nodes=[])


def _resolve_args(raw: dict, results: dict[str, Any]) -> dict:
    """解析 $n1.field 引用（doc 02 §7.1）。"""
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, str) and v.startswith("$"):
            ref, _, field = v[1:].partition(".")
            out[k] = (results.get(ref, {}).get("data") or {}).get(field)
        else:
            out[k] = v
    return out


def _new_action_id(trace_id: str, node_id: str) -> str:
    return f"pa_{hashlib.sha256((trace_id + node_id).encode()).hexdigest()[:10]}"


def _receipt(node: dict, data: dict, risk: str) -> dict:
    return {"type": "receipt", "payload": dict(
        title="转账成功" if node["tool"] == "transfer" else "操作完成",
        amount=data.get("amount"), counterparty=data.get("counterparty"),
        detail=[{"label": "交易号", "value": data.get("transaction_id", "")},
                {"label": "余额", "value": f"¥{data.get('balance_after', 0):,.2f}"}],
        risk_level=risk, trace_id=data.get("trace_id", ""))}

async def guard_in(state: AgentState) -> dict:
    """前置检查（doc 03 §1.1）：熔断锁定优先 → 注入双路检测（doc 02 §9.1）→ 命中拒答+熔断计数。"""
    sid, tid, text = state["session_id"], state["trace_id"], state.get("user_text", "")

    st = breaker.status(sid)
    if st["locked"]:   # 锁定优先于一切放行（doc 06 §5.2）
        audit_mod.audit.record(tid, sid, "decision", {
            "stage": "guard_in", "breaker_locked": True, "trigger": st["trigger"],
            "seconds_left": st["seconds_left"], "reason": st["reason"]})
        return dict(security_flags={"breaker_locked": True}, status="rejected",
                    final_reply=f"会话已锁定：{st['reason']}。",
                    emitted=[{"type": "error", "payload": {
                        "code": "SESSION_LOCKED", "message": st["reason"],
                        "seconds_left": st["seconds_left"],
                        "retry_after_sec": st["seconds_left"]}}])

    res = await detector.detect(text)          # 规则路 + 模型路（超时以规则路为准，fail-closed）
    audit_mod.audit.record(tid, sid, "decision", {
        "stage": "guard_in", "injection_suspected": res.suspected,
        "hit_rules": res.hit_rules, "llm_verdict": res.llm_verdict, "path": res.paths})
    if res.suspected:
        row = breaker.record(sid, "injection",
                             reason=f"注入命中（{res.paths}）：{res.reason[:80]}")
        if row["state"] == "open" and row["scope"] == "session":
            audit_mod.audit.record(tid, sid, "decision", {
                "stage": "breaker", "event": "injection", "state": "open",
                "trigger": row["trigger"], "reason": row["reason"],
                "seconds_left": max(0, int(row["expires_at"] - time.time()))})
        return dict(security_flags={"injection_suspected": True}, status="rejected",
                    final_reply="抱歉，这条指令涉及安全风险，已被拦截（已记录审计）。",
                    emitted=[{"type": "error", "payload": {"code": "INJECTION_BLOCKED",
                                                           "message": "检测到可疑指令，已拦截",
                                                           "hit_rules": res.hit_rules}}])
    return dict(security_flags={"injection_suspected": False, "injection_path": res.paths})


async def intent_node(state: AgentState) -> dict:
    """意图识别：LLM 结构化输出优先（doc 03 §3.2），超时/非法 JSON/无密钥 → 规则回退（接口不变）。"""
    text = state.get("user_text", "")
    intent, path = None, "rule"
    if llm_enabled():
        intent = await llm_parse_intent(text, state)
        path = "llm" if intent else "rule_fallback"
    if intent is None:
        intent = parse_intent(text, state)
    intent["path"] = path
    audit_mod.audit.record(state["trace_id"], state["session_id"], "intent", intent)
    out: dict = dict(intent=intent)
    if intent.get("ambiguous"):
        q = intent.get("question") or "能再说具体一点吗？"
        out.update(status="waiting_clarify", final_reply=q,
                   emitted=[{"type": "final", "payload": {"text": q}}])
    return out


async def planner_node(state: AgentState) -> dict:
    """DAG 规划：LLM 优先（doc 03 §3.3，validate_dag 校验 + risk 服务端重盖章），失败回退静态 DAG。"""
    dag, path = None, "rule"
    if llm_enabled() and state["intent"].get("scenario") not in ("chat", "other"):
        dag = await llm_plan_dag(state["intent"], state)
        path = "llm" if dag else "rule_fallback"
    if dag is None:
        dag = plan_dag(state["intent"])
    dag["path"] = path
    audit_mod.audit.record(state["trace_id"], state["session_id"], "plan", dag)
    return dict(dag=dag, status="running")


def _confirm_detail(tool: str, args: dict, results: dict, state: AgentState) -> list[dict]:
    name = state.get("resolved_contact_name")
    if not name:
        for r in results.values():
            for it in (r.get("data") or {}).get("items") or []:
                if it.get("id") == args.get("to_contact_id"):
                    name = f"{it.get('name')}（尾号 {it.get('phone_tail', '')}）"
    if tool == "transfer":
        return [{"label": "收款人", "value": name or str(args.get("to_contact_id"))},
                {"label": "金额", "value": f"¥{float(args.get('amount') or 0):,.2f}"},
                {"label": "备注", "value": args.get("remark") or "—"}]
    return [{"label": "工具", "value": tool},
            {"label": "参数", "value": json.dumps({k: v for k, v in args.items() if k != "idempotency_key"},
                                                  ensure_ascii=False)}]

async def executor_node(state: AgentState) -> dict:
    """就绪节点 → 权限裁决 → 绿：放行；黄：确认中断；红：确认 + MFA 双中断（doc 02 §8.1 / doc 03 §7.2-7.3）。"""
    nodes = (state.get("dag") or {}).get("nodes", [])
    results = dict(state.get("node_results") or {})
    emitted: list[dict] = []
    logs: list[dict] = []

    for node in nodes:
        if node["id"] in results:
            continue
        args = _resolve_args(node.get("args") or {}, results)
        tool = node["tool"]
        ctx: dict = {}
        bstat = breaker.status(state["session_id"])
        if bstat["write_disabled"]:       # 熔断 T1：写操作禁用（查询类不受影响）
            ctx["write_disabled"] = True
        if tool in ("transfer", "aa_split"):
            ctx["today_transfer_total"] = await today_transfer_total(_client())
            ctx["contact_known"] = True if args.get("to_contact_id") else None
        decision = decide(tool, {**args, "amount": args.get("amount") or args.get("total_amount")}, ctx)
        logs.append({"node": node["id"], "tool": tool, "level": decision.level, "reasons": decision.reasons})
        audit_mod.audit.record(state["trace_id"], state["session_id"], "decision",
                               {"node": node["id"], "tool": tool, "level": decision.level,
                                "reasons": decision.reasons, "code": decision.code})

        if decision.denied:
            emitted.append({"type": "error", "payload": {"code": decision.code or "LIMIT_EXCEEDED",
                                                         "message": decision.reasons[0]}})
            reply = ("这笔金额超出单笔限额，请分笔办理或前往网点。"
                     if decision.code == "LIMIT_EXCEEDED" else decision.reasons[0])
            return dict(status="aborted", emitted=emitted, decision_log=logs, final_reply=reply)

        if decision.needs_confirm:
            action_id = _new_action_id(state["trace_id"], node["id"])
            card = dict(action_id=action_id, risk_level=decision.level, title="需要您的确认",
                        detail=_confirm_detail(tool, args, results, state),
                        consequence="实时到账，无法撤回" if tool == "transfer" else "提交后立即生效",
                        expires_in_sec=CONFIRM_TTL_SEC, upgrade_reasons=decision.reasons)
            PENDING_ACTIONS[action_id] = dict(action_id=action_id, session_id=state["session_id"],
                                              node_id=node["id"], tool=tool, args=args,
                                              risk_level=decision.level, status="pending",
                                              card=card,   # 快照恢复（doc 04 §7）：刷新/重连后
                                              # 原样重放同一张卡，服务端唯一事实源
                                              expires_at=time.time() + CONFIRM_TTL_SEC)
            ans = interrupt({"type": "confirm_card", "payload": card})
            approved = bool((ans or {}).get("approved"))
            audit_mod.audit.record(state["trace_id"], state["session_id"], "confirm",
                                   {"action_id": action_id, "approved": approved, "level": decision.level})
            if not approved:
                PENDING_ACTIONS.patch(action_id, status="rejected")
                return dict(status="aborted", decision_log=logs,
                            emitted=[{"type": "final", "payload": {"text": "已取消本次操作。"}}],
                            final_reply="已取消本次操作。")
            PENDING_ACTIONS.patch(action_id, status="confirmed")

            if decision.needs_mfa:
                ch_id = f"mfa_{action_id}"
                MFA_CHALLENGES[ch_id] = dict(challenge_id=ch_id, session_id=state["session_id"],
                                             action_id=action_id,
                                             code=_stable_code(state["trace_id"] + node["id"]),
                                             attempts=0, status="pending",
                                             expires_at=time.time() + MFA_TTL_SEC)
                ans2 = interrupt({"type": "mfa_request", "payload": dict(
                    challenge_id=ch_id, type="sms", target_masked="138****6688",
                    expires_in_sec=MFA_TTL_SEC, attempts_left=MFA_MAX_ATTEMPTS)})
                passed = bool((ans2 or {}).get("mfa_passed"))
                audit_mod.audit.record(state["trace_id"], state["session_id"], "confirm",
                                       {"challenge_id": ch_id, "mfa_passed": passed})
                if not passed:
                    MFA_CHALLENGES.patch(ch_id, status="failed")
                    return dict(status="aborted", decision_log=logs,
                                emitted=[{"type": "final", "payload": {"text": "验证失败，操作已取消。"}}],
                                final_reply="验证失败，操作已取消。")
                MFA_CHALLENGES.patch(ch_id, status="passed")

        return dict(current_node_id=node["id"], decision_log=logs, emitted=emitted)

    return dict(status="done", decision_log=logs)

async def tool_dispatch_node(state: AgentState) -> dict:
    """执行当前节点 → bank-core（幂等键 = trace_id + node_id，doc 02 §3 幂等设计）。"""
    node_id = state.get("current_node_id")
    node = {n["id"]: n for n in (state.get("dag") or {}).get("nodes", [])}.get(node_id)
    if node is None:
        return dict(status="done")
    args = _resolve_args(node.get("args") or {}, state.get("node_results") or {})
    # 幂等键全工具覆盖：transfer/aa_split/purchase/redeem 等写端点 bank-core 强制要求
    # Idempotency-Key（doc 02 §3.1）；GET 端点忽略该参数，键恒为 trace_id:node_id。
    args.setdefault("idempotency_key", f"{state['trace_id']}:{node_id}")
    t0 = time.perf_counter()
    result = await run_tool(node["tool"], args, _client())
    ms = int((time.perf_counter() - t0) * 1000)
    results = dict(state.get("node_results") or {})
    results[node_id] = result
    summary = _summarize(node["tool"], result)
    audit_mod.audit.record(state["trace_id"], state["session_id"], "tool_call",
                           {"node": node_id, "tool": node["tool"], "ok": result["ok"], "duration_ms": ms,
                            "args": {k: v for k, v in args.items() if k != "idempotency_key"},
                            "summary": summary})
    # 熔断 T1 计数（连续失败 → 写操作禁用；成功清零，doc 02 §9.4）
    b_row = breaker.record(state["session_id"], "tool_ok" if result["ok"] else "tool_fail")
    if b_row["state"] == "open":
        audit_mod.audit.record(state["trace_id"], state["session_id"], "decision",
                               {"stage": "breaker", "state": "open", "scope": b_row["scope"],
                                "trigger": b_row["trigger"], "reason": b_row["reason"],
                                "seconds_left": max(0, int(b_row["expires_at"] - time.time()))})
    msgs = [{"type": "tool_progress", "payload": dict(node_id=node_id, tool=node["tool"],
             status="done" if result["ok"] else "failed", duration_ms=ms, result_summary=summary)}]
    out: dict = dict(node_results=results, current_node_id=None, emitted=msgs)

    if result["ok"] and node["tool"] == "resolve_contact":
        items = (result["data"] or {}).get("items") or []
        if len(items) > 1:
            clarify = dict(question=f'找到 {len(items)} 位"{args.get("keyword")}"，请选择：',
                           options=[dict(id=it["id"], primary=f"{it['name']} · 尾号 {it.get('phone_tail')}",
                                         secondary=it.get("remark", "")) for it in items])
            out.update(status="waiting_clarify", clarify=clarify, final_reply=clarify["question"],
                       emitted=msgs + [{"type": "clarify_options", "payload": clarify}])
        elif len(items) == 1:
            result["data"]["contact_id"] = items[0]["id"]
            result["data"]["contact_name"] = items[0]["name"]
    if not result["ok"]:
        # 失败文案透传银行/执行器原始 message（用户可读，如 M3#2 R4 风险拒绝提示）
        msg = str((result.get("error") or {}).get("message") or "这步操作没有成功")
        out.update(status="aborted", final_reply=f"{msg}，已停止后续步骤。",
                   emitted=msgs + [{"type": "error", "payload": result["error"]}])
    return out


def reflector_node(state: AgentState) -> dict:
    if state.get("status") in ("aborted", "waiting_clarify"):
        return {}
    nodes = (state.get("dag") or {}).get("nodes", [])
    results = state.get("node_results") or {}
    if all(n["id"] in results for n in nodes):
        return dict(status="done")
    return dict(status="continue")


def _render_reply_parts(state: AgentState) -> tuple[list[str], list[dict]]:
    """从工具结果渲染回复文本与回执（数值全部来自 node_results，服务端原样给前端）。"""
    results = state.get("node_results") or {}
    levels = {log["node"]: log["level"] for log in (state.get("decision_log") or [])}
    texts: list[str] = []
    receipts: list[dict] = []
    for node_id, r in results.items():
        if not r.get("ok"):
            continue
        data = r.get("data") or {}
        if isinstance(data.get("items"), list):
            for a in data["items"]:
                if isinstance(a, dict) and a.get("type") == "checking":
                    texts.append(f"您的活期账户余额为 ¥{a['balance']:,.2f}。")
        if data.get("code") in ("OK", "IDEMPOTENT_REPLAY") and "balance_after" in data \
                and data.get("counterparty"):
            texts.append(f"已向 {data.get('counterparty')} 转账 ¥{data.get('amount'):,.2f}，"
                         f"交易号 {data.get('transaction_id')}，余额 ¥{data.get('balance_after'):,.2f}。")
            receipts.append({"type": "receipt", "payload": dict(
                title="转账成功", amount=data.get("amount"), counterparty=data.get("counterparty"),
                detail=[{"label": "交易号", "value": data.get("transaction_id", "")},
                        {"label": "余额", "value": f"¥{data.get('balance_after', 0):,.2f}"}],
                risk_level=levels.get(node_id, "yellow"), trace_id=state["trace_id"])})
        if data.get("code") == "SCHEDULED":
            texts.append(f"已创建定时转账任务，将于 {data.get('next_run_at')} 执行。")
        if data.get("requests"):
            texts.append(f"AA 收款单已生成 {len(data['requests'])} 笔，每人 ¥{data.get('share'):,.2f}。")
        # ── M3 六场景模板（数值全部来自 data 原值，顺序从具体到宽泛）──
        if data.get("code") == "OK" and "holding_amount" in data:      # 理财申购
            texts.append(f"已申购 {data.get('product_name')} ¥{data.get('amount'):,.2f}，"
                         f"活期余额 ¥{data.get('balance_after'):,.2f}。")
        if data.get("code") == "OK" and "payout" in data:              # 理财赎回
            texts.append(f"已赎回 ¥{data.get('redeemed'):,.2f}（含收益 ¥{data.get('profit_settled'):,.2f}），"
                         f"到账 ¥{data.get('payout'):,.2f}，余额 ¥{data.get('balance_after'):,.2f}。")
        if "total_expense" in data:                                     # 账单分类统计
            top = "、".join(f"{i['category']} ¥{i['amount']:,.2f}" for i in (data.get("items") or [])[:3])
            texts.append(f"{data.get('period')} 共支出 ¥{data.get('total_expense'):,.2f}（{top or '无支出'}）。")
        if "rules" in data and isinstance(data.get("items"), list):     # 异常交易
            if data["items"]:
                t0 = data["items"][0]
                texts.append(f"检测到 {data.get('total')} 笔可疑支出，最大一笔 {t0.get('counterparty')} "
                             f"¥{t0.get('amount'):,.2f}（{';'.join(t0.get('reasons') or [])}）。")
            else:
                texts.append(f"{data.get('period')} 未检测到异常支出。")
        if "expense" in data and "total_expense" not in data:           # 月度报告
            texts.append(f"{data.get('period')} 月报：收入 ¥{data.get('income'):,.2f}，"
                         f"支出 ¥{data.get('expense'):,.2f}。")
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict) and "merchant" in items[0]:
            subs = "、".join(f"{i.get('merchant')} ¥{i.get('amount'):,.2f}/{i.get('cycle', '月')}"
                             for i in items[:3])
            texts.append(f"检测到 {data.get('total', len(items))} 项订阅扣费：{subs}。")
        if data.get("code") == "OK" and "saved_monthly" in data:        # 取消订阅
            texts.append(f"已取消订阅，每月可省 ¥{data.get('saved_monthly'):,.2f}。")
        if data.get("recommend") and isinstance(items, list):           # 理财推荐
            top = "、".join(f"{i.get('name')}（年化 {i.get('annual_yield')}%，R{i.get('risk_level')}）"
                            for i in items[:3])
            texts.append(f"为您推荐：{top}。")
        if isinstance(items, list) and items and isinstance(items[0], dict) \
                and "product_name" in items[0] and "profit" in items[0]:   # 持仓查询
            pos = "、".join(f"{i.get('product_name')} ¥{i.get('amount'):,.2f}" for i in items[:3])
            texts.append(f"当前持仓 {len(items)} 笔：{pos}。")
        if data.get("code") == "OK" and data.get("card_no_masked"):      # 卡片操作
            line = f"卡片（{data.get('card_no_masked')}）当前状态「{data.get('status')}」"
            if isinstance(data.get("daily_limit"), (int, float)):
                line += f"，单日限额 ¥{data['daily_limit']:,.2f}"
            texts.append(line + "。")
        if data.get("code") == "OK" and "frozen_amount" in data:         # 资金锁定/解锁
            verb = "已锁定" if data.get("reason") else "已解冻"
            texts.append(f"资金{verb}（{data.get('reason') or '手动解锁'}），"
                         f"当前冻结合计 ¥{data.get('frozen_amount'):,.2f}，可用 ¥{data.get('available'):,.2f}。")
        if data.get("code") == "OK" and data.get("task_type"):           # 定时任务创建
            tt = data.get("task_type")
            payload = data.get("payload") or {}
            if tt == "reminder":
                texts.append(f"已创建提醒：{payload.get('text', '待办')}（{data.get('next_run_at')}）。")
            elif tt == "fund_unlock":
                texts.append(f"已安排 {data.get('next_run_at')} 自动解冻资金。")
            elif tt == "transfer":
                texts.append(f"已创建每月定时转账 ¥{payload.get('amount', 0):,.2f}，"
                             f"下次 {data.get('next_run_at')} 执行。")
            elif tt == "gift_order":
                its = payload.get("items") or []
                its = "、".join(its) if isinstance(its, list) else str(its)
                texts.append(f"已预订礼品（{its}，¥{payload.get('amount', 0):,.2f}），"
                             f"将于 {data.get('next_run_at')} 下单。")
    return texts, receipts


def _safe_reply(results: dict) -> str:
    """verifier 重生成（doc 02 §9.2）：独立于首版渲染器，只复述工具结果原值。"""
    texts: list[str] = []
    for r in (results or {}).values():
        if not isinstance(r, dict) or not r.get("ok"):
            continue
        data = r.get("data") or {}
        if isinstance(data.get("items"), list):
            for a in data["items"]:
                if isinstance(a, dict) and a.get("type") == "checking":
                    texts.append(f"您的活期账户余额为 ¥{a['balance']:,.2f}。")
        if "balance_after" in data and data.get("counterparty"):
            texts.append(f"已向 {data.get('counterparty')} 转账 ¥{data.get('amount'):,.2f}，"
                         f"交易号 {data.get('transaction_id')}，余额 ¥{data['balance_after']:,.2f}。")
        if data.get("requests"):
            texts.append(f"AA 收款单已生成 {len(data['requests'])} 笔，每人 ¥{data.get('share'):,.2f}。")
        if data.get("code") == "SCHEDULED":
            texts.append(f"已创建定时任务，将于 {data.get('next_run_at')} 执行。")
    return " ".join(texts)


async def responder_node(state: AgentState) -> dict:
    status = state.get("status")
    if status == "waiting_clarify":
        return {}
    results = state.get("node_results") or {}
    texts, receipts = _render_reply_parts(state)
    reply = " ".join(texts) or (state.get("final_reply") or "已完成。")
    if status in ("aborted", "rejected") and state.get("final_reply"):
        reply = state["final_reply"]
    reply_path = "template"

    # ── M3 Step 2：LLM 回复优先（doc 03 §3.5）；工具结果 wrap_untrusted 包裹后才进 LLM 上下文
    #    （doc 02 §9.1 数据隔离唯一入口）。拒答/中止话术不经 LLM；LLM 产物先过 verifier，不过→模板。──
    if llm_enabled() and results and status not in ("aborted", "rejected"):
        untrusted = wrap_untrusted(json.dumps(results, ensure_ascii=False, default=str))
        goal = (state.get("dag") or {}).get("goal") or state.get("user_text", "")
        cand = (await llm_chat(load_prompt("system"),
                               render_prompt("responder", node_results=untrusted, goal=goal)) or "")
        cand = cand.strip().strip('"').strip()
        if cand:
            v0 = verifier.verify(cand, results)
            audit_mod.audit.record(state["trace_id"], state["session_id"], "decision", {
                "stage": "reply_llm", "passed": v0.passed,
                "hallucinated_numbers": list(v0.hallucinated_numbers)})
            if v0.passed:
                reply, reply_path = cand, "llm"

    # ── M2#2 输出幻觉校验（doc 02 §9.2 / doc 03 §10）：数值 ⊆ 工具结果；失败重生成 ≤2 → 保守话术
    v = verifier.verify(reply, results)
    attempts, first_halluc = 1, list(v.hallucinated_numbers)
    while not v.passed and attempts < 3:
        reply = _safe_reply(results) or CONSERVATIVE_REPLY
        reply_path = "template"
        attempts += 1
        v = verifier.verify(reply, results)
    if not v.passed:
        reply = CONSERVATIVE_REPLY
        reply_path = "template"
    audit_mod.audit.record(state["trace_id"], state["session_id"], "decision", {
        "stage": "verifier", "passed": v.passed, "attempts": attempts,
        "hallucinated_numbers": first_halluc, "regenerated": bool(v.passed and attempts > 1),
        "reply_path": reply_path})
    audit_mod.audit.record(state["trace_id"], state["session_id"], "reply", {"text": reply})
    return dict(final_reply=reply, status=status if status in ("aborted", "rejected") else "done",
                emitted=receipts + [{"type": "final", "payload": {"text": reply}}])


def _summarize(tool: str, result: dict) -> str:
    if not result["ok"]:
        return f"失败：{result['error']['message']}"
    data = result["data"] or {}
    if tool == "resolve_contact":
        items = data.get("items") or []
        return f"{len(items)} 位匹配：" + " / ".join(f"{i['name']}({i.get('phone_tail')})" for i in items[:3])
    if "balance_after" in data:
        return f"{data.get('counterparty')} ¥{data.get('amount', 0):,.2f}，余额 ¥{data['balance_after']:,.2f}"
    if tool == "query_balance":
        return "、".join(f"{a['type']} ¥{a['balance']:,.2f}" for a in data.get("items", []))
    return json.dumps(data, ensure_ascii=False)[:120]

# ── LLM 编排（M3 Step 2，doc 03 §3）：意图/规划 LLM 优先 + JSON 校验 + 规则回退 ──
TOOL_ARGS_HINT: dict[str, str] = {
    "query_balance": "查活期/定期余额；无参数",
    "query_transactions": "查流水；account_id?, category?, keyword?, from_?, to?, page?",
    "resolve_contact": "按姓名/备注查联系人；keyword",
    "change_password": "修改登录密码；old_password, new_password",
    "transfer": "转账（带 schedule_time 转为定时任务）；to_contact_id, amount, remark?, schedule_time?",
    "aa_split": "AA 收款（N 人拆 N-1 笔）；total_amount, member_count(人数-1), keyword?, contact_ids?, remark?",
    "analyze_billing": "账单分析；kind=category|anomalies|report, period=YYYY-MM?",
    "detect_subscriptions": "识别周期性扣费订阅；无参数",
    "cancel_subscription": "取消订阅；subscription_id 或 merchant",
    "query_wealth_products": "理财货架；risk_max?, type?",
    "query_holdings": "持仓查询；无参数",
    "recommend_wealth": "理财推荐 Top5；risk_max?",
    "purchase_wealth": "理财申购；product_id 或 product_name, amount",
    "redeem_wealth": "理财赎回；holding_id 或 product_name, amount",
    "apply_virtual_card": "申请虚拟卡；无参数",
    "adjust_card_limit": "调卡额度；card_id 或 card_tail, daily_limit",
    "freeze_card": "冻结卡；card_id 或 card_tail",
    "unfreeze_card": "解冻卡；card_id 或 card_tail",
    "report_card_loss": "挂失；card_id 或 card_tail",
    "cancel_card_loss": "解挂；card_id 或 card_tail",
    "freeze_funds": "锁定活期资金；amount, reason?",
    "unfreeze_funds": "解冻资金；amount",
    "create_scheduled_task": "建定时任务；task_type, payload, next_run_at, recurrence?",
    "place_gift_order": "礼品下单（定时）；items, amount, recipient, next_run_at?",
}


def render_tool_catalog() -> str:
    """LLM 规划用工具目录（doc 03 §3.3）：名称/参数/端点——绝不含风险等级（risk 只由服务端裁决）。"""
    return "\n".join(f"- {t.name}：{TOOL_ARGS_HINT.get(t.name, '')} → {t.bank}"
                     for t in TOOL_SPECS.values())


def validate_dag(data: dict | None) -> dict | None:
    """LLM 规划产物校验：1-6 节点、工具白名单、ID 唯一、depends_on 合法且无环（DFS 三色）；
    通过后 risk 一律用服务端注册表重盖章——LLM 自报 risk 直接丢弃（doc 02 §8.3 铁律）。"""
    if not isinstance(data, dict):
        return None
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not 1 <= len(raw_nodes) <= 6:
        return None
    nodes: list[dict] = []
    for i, n in enumerate(raw_nodes):
        if not isinstance(n, dict):
            return None
        tool = str(n.get("tool") or "")
        if tool not in TOOL_SPECS:
            return None
        nid = str(n.get("id") or f"n{i + 1}")
        if any(x["id"] == nid for x in nodes):
            return None
        args = n.get("args") if isinstance(n.get("args"), dict) else {}
        deps = n.get("depends_on") if isinstance(n.get("depends_on"), list) else []
        nodes.append(dict(id=nid, tool=tool, args=dict(args),
                          depends_on=[str(d) for d in deps], risk=spec(tool).base_risk))
    by_id = {n["id"]: n for n in nodes}
    if any(d not in by_id for n in nodes for d in n["depends_on"]):
        return None
    mark: dict[str, int] = {}              # 1=在栈 2=完成

    def _acyclic(nid: str) -> bool:
        if mark.get(nid) == 1:
            return False
        if mark.get(nid) == 2:
            return True
        mark[nid] = 1
        for d in by_id[nid]["depends_on"]:
            if not _acyclic(d):
                return False
        mark[nid] = 2
        return True

    if not all(_acyclic(n["id"]) for n in nodes):
        return None
    return dict(goal=str(data.get("goal") or "LLM 规划"), nodes=nodes)


_LLM_SCENARIOS = {"transfer", "billing", "wealth", "subscription", "card",
                  "cross_scenario", "chat", "other", "query_balance", "aa_split",
                  "change_password", "query_transactions"}


async def llm_parse_intent(text: str, state: AgentState) -> dict | None:
    """LLM 意图识别（doc 03 §3.2）：带历史指代消解；JSON 契约/场景白名单校验失败 → None（规则回退）。"""
    history = "\n".join(f"- {h.get('text')}（{h.get('scenario')}）"
                        for h in (state.get("history") or [])[-8:]) or "（无）"
    raw = await llm_chat(load_prompt("system"),
                         render_prompt("intent", history=history, user_input=text))
    data = extract_json(raw)
    if not data:
        return None
    scenario = str(data.get("scenario") or "")
    if scenario not in _LLM_SCENARIOS:
        return None
    try:
        confidence = float(data.get("confidence", 0.8))
    except (TypeError, ValueError):
        confidence = 0.8
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    ambiguous = bool(data.get("ambiguous"))
    intent = dict(scenario=scenario, confidence=confidence, ambiguous=ambiguous,
                  slots=dict(slots), question=str(data.get("clarify_question") or ""),
                  goal=str(data.get("goal") or ""))
    if scenario == "transfer":
        _normalize_transfer_slots(intent)
    if ambiguous and not intent["question"]:
        intent["question"] = "能再说具体一点吗？"
    return intent


def _normalize_transfer_slots(intent: dict) -> None:
    """LLM 转账槽位 → 执行参数约定：payee→keyword/contact_id，amount→float，AA 变体归位。"""
    slots = intent["slots"]
    payee = str(slots.pop("payee", "") or "").strip()
    if payee:
        if re.fullmatch(r"c\d{3}", payee):
            slots.setdefault("contact_id", payee)
        else:
            slots.setdefault("keyword", payee)
    try:
        if slots.get("amount") is not None:
            slots["amount"] = float(slots["amount"])
    except (TypeError, ValueError):
        slots.pop("amount", None)
    if slots.get("aa") or (slots.get("total_amount") and slots.get("member_count")):
        intent["scenario"] = "aa_split"


async def llm_plan_dag(intent: dict, state: AgentState) -> dict | None:
    """LLM 规划（doc 03 §3.3）：catalog + intent + 上下文 → DAG JSON；validate_dag 不过 → None。"""
    context = {"prev_slots": state.get("prev_slots"),
               "resolved_contact": state.get("resolved_contact_id"),
               "recent_history": (state.get("history") or [])[-3:]}
    raw = await llm_chat(load_prompt("system"),
                         render_prompt("planner",
                                       tool_catalog=render_tool_catalog(),
                                       intent=json.dumps(intent, ensure_ascii=False),
                                       context=json.dumps(context, ensure_ascii=False)))
    return validate_dag(extract_json(raw))


# ─────────────────────────── 路由与构图 ───────────────────────────
def route_after_guard(state: AgentState) -> str:
    return "blocked" if state.get("status") == "rejected" else "intent"


def route_after_intent(state: AgentState) -> str:
    return "clarify" if state.get("status") == "waiting_clarify" else "planner"


def route_after_executor(state: AgentState) -> str:
    return "dispatch" if state.get("current_node_id") else "respond"


def route_after_reflector(state: AgentState) -> str:
    return "continue" if state.get("status") == "continue" else "respond"


_client_factory = None


def set_client_factory(factory) -> None:
    """测试注入点：替换 bank-core 客户端工厂。"""
    global _client_factory
    _client_factory = factory


def _client() -> BankClient:
    return _client_factory() if _client_factory else BankClient()


_GRAPH = None


_SAVER = None
_SAVER_LOOP = None
_GRAPH_SAVER = None


async def init_checkpointer(path: str | None = None) -> None:
    """M2：AsyncSqliteSaver（doc 03 §7.1）——`ainvoke` 链路要求异步 checkpointer。

    - 在 FastAPI lifespan 调用；状态持久化到 agent.db，重启不丢中断；
    - `isolation_level=None`（autocommit）：checkpoint 写不持有隐式事务，
      否则 saver 空闲持写锁 → guard_in 审计 INSERT 阻塞至 busy_timeout（挂起/locked）；
    - 事件循环更换（pytest 每模块独立 TestClient）→ 关旧连接重建，图随之重建（get_graph）。
    """
    global _SAVER, _SAVER_LOOP
    loop = asyncio.get_running_loop()
    if _SAVER is not None and _SAVER_LOOP is not loop:
        old, _SAVER = _SAVER, None
        try:
            await old.conn.close()          # aiosqlite 工作线程与循环无关，可跨循环安全关闭
        except Exception:  # noqa: BLE001
            pass
    if _SAVER is None:
        conn = await aiosqlite.connect(path or AGENT_DB_PATH, isolation_level=None, timeout=30)
        await conn.execute("PRAGMA busy_timeout=30000")
        _SAVER = AsyncSqliteSaver(conn)
        _SAVER_LOOP = loop


def _checkpointer():
    if _SAVER is None:
        raise RuntimeError("AsyncSqliteSaver 未初始化：请先 await init_checkpointer()（main.lifespan）")
    return _SAVER


def build_graph():
    """七节点图（doc 02 §6.2）；checkpointer = SqliteSaver（doc 03 §7.1）。"""
    g = StateGraph(AgentState)
    for name, fn in (("guard_in", guard_in), ("intent", intent_node), ("planner", planner_node),
                     ("executor", executor_node), ("tool_dispatch", tool_dispatch_node),
                     ("reflector", reflector_node), ("responder", responder_node)):
        g.add_node(name, fn)
    g.add_edge(START, "guard_in")
    g.add_conditional_edges("guard_in", route_after_guard, {"blocked": "responder", "intent": "intent"})
    g.add_conditional_edges("intent", route_after_intent, {"clarify": "responder", "planner": "planner"})
    g.add_edge("planner", "executor")
    g.add_conditional_edges("executor", route_after_executor,
                            {"dispatch": "tool_dispatch", "respond": "responder"})
    g.add_edge("tool_dispatch", "reflector")
    g.add_conditional_edges("reflector", route_after_reflector,
                            {"continue": "executor", "respond": "responder"})
    g.add_edge("responder", END)
    return g.compile(checkpointer=_checkpointer())


def get_graph():
    global _GRAPH, _GRAPH_SAVER
    if _GRAPH is None or _GRAPH_SAVER is not _SAVER:   # checkpointer 重建（换循环）→ 图随之重建
        _GRAPH = build_graph()
        _GRAPH_SAVER = _SAVER
    return _GRAPH


# ───────── 追加导入（拆分写入，置于文件尾，模块级生效）─────────
import asyncio  # noqa: E402,F401
import aiosqlite  # noqa: E402
import json  # noqa: E402,F401
import time  # noqa: E402

from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402

from ..config import CONFIRM_TTL_SEC, MFA_MAX_ATTEMPTS, MFA_TTL_SEC  # noqa: E402

