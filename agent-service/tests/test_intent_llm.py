"""M3 Step 2：LLM 意图/规划/回复编排（doc 03 §3）+ 规则降级六场景 + 执行器实体解析。

离线可跑：LLM 走 llm.set_backend() 注入的假后端（不依赖外网端点）；
图级用例用 DictBank 经 set_client_factory 注入，不触达真实 bank-core。
"""
import asyncio
import json
import re
from datetime import date

import pytest

from app import llm
from app.graph import agent_graph as g
from app.tools.bank_client import BankError
from app.tools.executor import run_tool
from app.tools.specs import spec


class FakeLLM:
    """按提示词特征路由的假 LLM：intent/planner 返回预置 JSON，responder 返回预置文本。"""

    def __init__(self, intent=None, plan=None, reply="已为您完成。"):
        self.intent, self.plan, self.reply = intent, plan, reply
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system, user, *, model=None, temperature=0.2, max_tokens=800):
        self.calls.append((system, user))
        if "分析用户最新一条消息" in user:
            return json.dumps(self.intent, ensure_ascii=False) if self.intent is not None else None
        if "生成子任务 DAG" in user:
            return json.dumps(self.plan, ensure_ascii=False) if self.plan is not None else None
        return self.reply


class DictBank:
    """按路径查表的假 bank-core 客户端。"""

    def __init__(self, routes: dict):
        self.routes, self.calls = routes, []

    async def get(self, path, **params):
        self.calls.append(("GET", path, params))
        if path not in self.routes:
            raise BankError("NOT_FOUND", f"DictBank 未实现 {path}", 404)
        return self.routes[path]

    async def post(self, path, payload, idempotency_key=None):
        self.calls.append(("POST", path, payload, idempotency_key))
        return {"code": "OK"}


@pytest.fixture(autouse=True)
def _reset_llm_backend():
    yield
    llm.set_backend(None)
    g.set_client_factory(None)


def _state(**kw):
    base = dict(session_id="t", trace_id="tr_t", user_text="", history=[])
    base.update(kw)
    return base


# ── LLM 客户端与提示词 ──────────────────────────────────────────
def test_extract_json_variants():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('前置说明 {"a": "含}括号"} 后置') == {"a": "含}括号"}
    assert llm.extract_json("没有 JSON") is None
    assert llm.extract_json("[1, 2]") is None
    assert llm.extract_json(None) is None


def test_chat_without_backend_or_key_returns_none():
    assert asyncio.run(llm.chat("s", "u")) is None     # 无 key 无后端 → None（降级）


def test_prompts_loaded_from_md_files():
    assert "智银助手" in llm.load_prompt("system")
    assert "{user_input}" in llm.load_prompt("intent")
    out = llm.render_prompt("intent", history="（无）", user_input="你好")
    assert "（无）" in out and "你好" in out and "{history}" not in out


# ── LLM 意图（doc 03 §3.2）──────────────────────────────────────
def test_llm_intent_valid_transfer_slots_normalized():
    llm.set_backend(FakeLLM(intent={
        "scenario": "transfer", "goal": "给王芳转账", "confidence": 0.9,
        "slots": {"payee": "王芳", "amount": "500", "remark": "生日红包"}, "ambiguous": False}))
    intent = asyncio.run(g.llm_parse_intent("给王芳转 500", _state()))
    assert intent["scenario"] == "transfer" and intent["goal"] == "给王芳转账"
    assert intent["slots"]["keyword"] == "王芳" and intent["slots"]["amount"] == 500.0


def test_llm_intent_garbage_falls_back_to_rule():
    llm.set_backend(FakeLLM(intent=None))              # None → chat 返回 None → extract None
    assert asyncio.run(g.llm_parse_intent("给张伟转 200 元", _state())) is None
    intent = g.parse_intent("给张伟转 200 元", _state())
    assert intent["scenario"] == "transfer" and intent["slots"]["amount"] == 200.0


def test_llm_intent_unknown_scenario_rejected():
    llm.set_backend(FakeLLM(intent={"scenario": "wire_fraud", "slots": {}, "ambiguous": False}))
    assert asyncio.run(g.llm_parse_intent("随便", _state())) is None


def test_llm_intent_ambiguous_default_question():
    llm.set_backend(FakeLLM(intent={"scenario": "transfer", "slots": {}, "ambiguous": True}))
    intent = asyncio.run(g.llm_parse_intent("转点钱", _state()))
    assert intent["ambiguous"] and intent["question"]


def test_llm_intent_history_rendered_for_coreference():
    fake = FakeLLM(intent={"scenario": "transfer", "slots": {"payee": "王芳", "amount": 500},
                           "ambiguous": False, "confidence": 0.95})
    llm.set_backend(fake)
    state = _state(history=[{"text": "给王芳转了 500", "scenario": "transfer", "slots": {}}])
    asyncio.run(g.llm_parse_intent("再给她转一次", state))
    prompt = fake.calls[0][1]
    assert "给王芳转了 500" in prompt and "再给她转一次" in prompt   # 历史入 prompt（指代消解）


# ── M3#7 规则路代词/省略回填（doc 03 §3.2 规则 2，离线确定）────────
def _hist_transfer(**slots):
    base = {"keyword": "王芳", "amount": 500.0, "remark": "家用"}
    base.update(slots)
    return [{"text": "给王芳转 500", "scenario": "transfer", "slots": base}]


def test_rule_pronoun_refill_same_amount():
    intent = g.parse_intent("再给她转一次", _state(history=_hist_transfer()))
    assert intent["scenario"] == "transfer" and not intent.get("ambiguous")
    assert intent["slots"]["keyword"] == "王芳" and intent["slots"]["amount"] == 500.0
    assert intent["slots"]["remark"] == "家用"


def test_rule_pronoun_refill_amount_override():
    intent = g.parse_intent("再给她转 300", _state(history=_hist_transfer()))
    assert intent["scenario"] == "transfer" and not intent.get("ambiguous")
    assert intent["slots"]["keyword"] == "王芳" and intent["slots"]["amount"] == 300.0


def test_rule_pronoun_refill_contact_id_preferred():
    history = _hist_transfer(contact_id="c003", keyword="王芳")
    intent = g.parse_intent("同样再转一次", history and _state(history=history))
    assert intent["scenario"] == "transfer" and not intent.get("ambiguous")
    assert intent["slots"]["contact_id"] == "c003" and intent["slots"]["amount"] == 500.0


def test_rule_pronoun_refill_no_history_falls_through():
    intent = g.parse_intent("再给她转一次", _state())
    assert intent["scenario"] in ("chat", "other") or intent.get("ambiguous")


def test_rule_pronoun_refill_non_transfer_untouched():
    intent = g.parse_intent("我的余额", _state(history=_hist_transfer()))
    assert intent["scenario"] == "query_balance"


# ── LLM 规划：DAG 校验（doc 03 §3.3 规则）───────────────────────
def test_validate_dag_valid_and_risk_restamped():
    dag = g.validate_dag({"goal": "转账", "nodes": [
        {"id": "n1", "tool": "resolve_contact", "args": {"keyword": "王芳"}, "depends_on": []},
        {"id": "n2", "tool": "transfer", "depends_on": ["n1"], "risk": "green",   # LLM 自报 green
         "args": {"to_contact_id": "$n1.contact_id", "amount": 500}}]})
    assert dag is not None and [n["id"] for n in dag["nodes"]] == ["n1", "n2"]
    n2 = dag["nodes"][1]
    assert n2["risk"] == spec("transfer").base_risk == "yellow"   # 服务端重盖章，LLM 自报被丢弃


def test_validate_dag_rejections():
    assert g.validate_dag(None) is None
    assert g.validate_dag({"nodes": []}) is None
    assert g.validate_dag({"nodes": [{"id": f"n{i}", "tool": "query_balance"}
                                     for i in range(7)]}) is None                    # >6 节点
    assert g.validate_dag({"nodes": [{"id": "n1", "tool": "hack_everything"}]}) is None  # 未知工具
    assert g.validate_dag({"nodes": [{"id": "n1", "tool": "query_balance"},
                                     {"id": "n1", "tool": "query_holdings"}]}) is None   # ID 重复
    assert g.validate_dag({"nodes": [{"id": "n1", "tool": "transfer", "depends_on": ["nX"]}]
                           }) is None                                                    # 引用未知节点
    assert g.validate_dag({"nodes": [{"id": "n1", "tool": "query_balance", "depends_on": ["n2"]},
                                     {"id": "n2", "tool": "query_holdings", "depends_on": ["n1"]}]
                           }) is None                                                    # 环


def test_tool_catalog_has_no_risk_levels():
    catalog = g.render_tool_catalog()
    assert catalog.count("\n") + 1 == 24               # 24 工具全量（doc 02 §5 唯一清单）
    assert "green" not in catalog and "yellow" not in catalog   # 风险等级不出 catalog
    assert "transfer" in catalog and "POST /api/transfers" in catalog


def test_llm_plan_dag_valid_then_invalid_fallback():
    llm.set_backend(FakeLLM(plan={"goal": "查余额",
                                  "nodes": [{"id": "n1", "tool": "query_balance", "args": {}}]}))
    dag = asyncio.run(g.llm_plan_dag({"scenario": "query_balance", "slots": {}}, _state()))
    assert dag and dag["nodes"][0]["tool"] == "query_balance"
    llm.set_backend(FakeLLM(plan={"nodes": [{"id": "n1", "tool": "not_a_tool"}]}))
    assert asyncio.run(g.llm_plan_dag({"scenario": "query_balance", "slots": {}}, _state())) is None
    llm.set_backend(FakeLLM(plan=None))
    assert asyncio.run(g.llm_plan_dag({"scenario": "query_balance", "slots": {}}, _state())) is None


# ── 规则意图降级路：M3 六场景 ────────────────────────────────────
def _prev_month() -> str:
    today = date.today()
    first = today.replace(day=1)
    from datetime import timedelta
    return (first - timedelta(days=1)).strftime("%Y-%m")


def test_rule_billing_category_with_period():
    intent = g.parse_intent("我上个月餐饮花了多少钱", _state())
    assert intent["scenario"] == "billing"
    assert intent["slots"]["kind"] == "category" and intent["slots"]["period"] == _prev_month()


def test_rule_billing_anomalies_this_month():
    intent = g.parse_intent("我这个月有哪些异常支出？", _state())
    assert intent["scenario"] == "billing" and intent["slots"]["kind"] == "anomalies"
    assert intent["slots"]["period"] == date.today().strftime("%Y-%m")


def test_rule_wealth_purchase_and_recommend():
    intent = g.parse_intent("我想买 1 万块的稳健添利 30 天", _state())   # doc 05 M3#2 原句
    assert intent["scenario"] == "wealth" and intent["slots"]["action"] == "purchase"
    assert intent["slots"]["amount"] == 10000.0
    assert "稳健添利 30 天" in intent["slots"]["product_name"]
    rec = g.parse_intent("有什么稳健理财推荐吗", _state())
    assert rec["slots"]["action"] == "recommend" and rec["slots"]["risk_max"] == 2


def test_rule_subscription_cancel_merchant():
    intent = g.parse_intent("帮我取消云存储的订阅", _state())
    assert intent["scenario"] == "subscription"
    assert intent["slots"]["action"] == "cancel" and intent["slots"]["merchant"] == "云存储"


def test_rule_card_loss_and_apply():
    intent = g.parse_intent("挂失尾号 6688 的卡", _state())
    assert intent["scenario"] == "card" and intent["slots"]["action"] == "report_loss"
    assert intent["slots"]["card_tail"] == "6688"
    assert g.parse_intent("帮我申请一张虚拟卡", _state())["slots"]["action"] == "apply"
    no_tail = g.parse_intent("冻结我的信用卡", _state())
    assert no_tail["ambiguous"] and "后四位" in no_tail["question"]


def test_rule_password_change():
    intent = g.parse_intent("把登录密码从 123456 改成 Abcdef12", _state())
    assert intent["scenario"] == "change_password"
    assert intent["slots"] == {"old_password": "123456", "new_password": "Abcdef12"}


def test_rule_monthly_transfer_becomes_scheduled_task():
    intent = g.parse_intent("每个月 1 号给房东转 3000 房租", _state())
    assert intent["scenario"] == "transfer" and intent["slots"]["recurrence"] == "monthly"
    dag = g.plan_dag(intent)
    assert [n["tool"] for n in dag["nodes"]] == ["resolve_contact", "create_scheduled_task"]
    n2 = dag["nodes"][1]
    assert n2["args"]["task_type"] == "transfer" and n2["args"]["recurrence"] == "monthly"
    assert n2["args"]["to_contact_id"] == "$n1.contact_id"
    assert re.match(r"\d{4}-\d{2}-01 09:00", n2["args"]["next_run_at"])


def test_rule_cross_birthday_full_slots():
    intent = g.parse_intent("我爱人下个月 15 号生日，帮我准备一下", _state())
    assert intent["scenario"] == "cross_scenario" and not intent["ambiguous"]
    today = date.today()
    month = today.month % 12 + 1
    year = today.year + (1 if today.month == 12 else 0)
    assert intent["slots"]["date"] == f"{year:04d}-{month:02d}-15"
    assert intent["slots"]["recipient"] == "爱人" and intent["slots"]["occasion"] == "生日"


def test_rule_cross_ambiguous_without_date():
    intent = g.parse_intent("我爱人生日帮我准备一下", _state())
    assert intent["ambiguous"] and "哪一天" in intent["question"]


def test_plan_dag_m3_branches():
    dag = g.plan_dag({"scenario": "billing", "slots": {"kind": "report", "period": "2026-08"}})
    assert dag["nodes"][0]["tool"] == "analyze_billing"
    assert dag["nodes"][0]["args"] == {"kind": "report", "period": "2026-08"}
    assert dag["nodes"][0]["risk"] == "green"

    dag = g.plan_dag({"scenario": "subscription", "slots": {"action": "cancel", "merchant": "云存储"}})
    assert dag["nodes"][0]["tool"] == "cancel_subscription"
    assert dag["nodes"][0]["args"] == {"merchant": "云存储"} and dag["nodes"][0]["risk"] == "yellow"

    dag = g.plan_dag({"scenario": "wealth", "slots": {"action": "purchase",
                                                      "product_name": "稳健添利 30 天", "amount": 10000}})
    assert dag["nodes"][0]["tool"] == "purchase_wealth" and dag["nodes"][0]["risk"] == "red"
    assert dag["nodes"][0]["args"] == {"product_name": "稳健添利 30 天", "amount": 10000}

    dag = g.plan_dag({"scenario": "card", "slots": {"action": "freeze", "card_tail": "6688"}})
    assert dag["nodes"][0]["tool"] == "freeze_card" and dag["nodes"][0]["args"]["card_tail"] == "6688"

    dag = g.plan_dag({"scenario": "cross_scenario",
                      "slots": {"occasion": "生日", "date": "2026-10-15", "recipient": "爱人",
                                "lock_amount": 1000, "budget": 600, "items": ["鲜花", "蛋糕"]}})
    tools = [n["tool"] for n in dag["nodes"]]
    assert tools == ["freeze_funds", "place_gift_order", "create_scheduled_task", "create_scheduled_task"]
    assert dag["nodes"][1]["depends_on"] == ["n1"]            # 先锁钱后下单
    assert dag["nodes"][1]["args"]["next_run_at"] == "2026-10-13 09:00"   # 生日前两天
    assert dag["nodes"][2]["args"]["next_run_at"] == "2026-10-14 09:00"   # 前一天提醒
    assert dag["nodes"][3]["args"]["task_type"] == "fund_unlock"
    assert dag["nodes"][3]["args"]["next_run_at"] == "2026-10-15 20:00"   # 当日解锁


# ── 执行器实体解析（业务标识 → ID；doc 03 §3.3 先查后写）────────
CARDS = {"items": [{"id": "cd001", "card_no_masked": "6228 **** **** 1234", "status": "active"},
                   {"id": "cd002", "card_no_masked": "6228 **** **** 6688", "status": "active"}]}


def test_resolve_card_by_tail():
    bank = DictBank({"/api/cards": CARDS})
    out = asyncio.run(run_tool("freeze_card", {"card_tail": "6688"}, bank))
    assert out["ok"] and bank.calls[-1][1] == "/api/cards/cd002/freeze"


def test_resolve_card_ambiguous_and_not_found():
    dup = {"items": [{"id": "cd001", "card_no_masked": "** 6688"},
                     {"id": "cd009", "card_no_masked": "** 6688"}]}
    out = asyncio.run(run_tool("freeze_card", {"card_tail": "6688"}, DictBank({"/api/cards": dup})))
    assert not out["ok"] and out["error"]["code"] == "CARD_AMBIGUOUS"
    out = asyncio.run(run_tool("freeze_card", {"card_tail": "0000"}, DictBank({"/api/cards": CARDS})))
    assert not out["ok"] and out["error"]["code"] == "CARD_NOT_FOUND"


def test_resolve_product_by_name_unique_vs_ambiguous():
    products = {"items": [{"id": "p004", "name": "稳健添利 30 天"},
                          {"id": "p001", "name": "安稳 365 天"}]}
    bank = DictBank({"/api/wealth/products": products})
    out = asyncio.run(run_tool("purchase_wealth",
                               {"product_name": "稳健添利 30 天", "amount": 10000}, bank))
    assert out["ok"] and bank.calls[-1][2]["product_id"] == "p004"
    both = {"items": [{"id": "p1", "name": "添利 A"}, {"id": "p2", "name": "添利 B"}]}
    out = asyncio.run(run_tool("purchase_wealth", {"product_name": "添利", "amount": 1},
                               DictBank({"/api/wealth/products": both})))
    assert not out["ok"] and out["error"]["code"] == "PRODUCT_AMBIGUOUS"


def test_resolve_holding_and_subscription_by_name():
    holdings = {"items": [{"id": "h001", "product_name": "安稳 365 天"}]}
    bank = DictBank({"/api/wealth/holdings": holdings})
    out = asyncio.run(run_tool("redeem_wealth", {"product_name": "安稳", "amount": 5000}, bank))
    assert out["ok"] and bank.calls[-1][2]["holding_id"] == "h001"

    subs = {"items": [{"id": "s001", "merchant": "视频会员", "status": "active"},
                      {"id": "s003", "merchant": "云存储", "status": "active"}]}
    bank = DictBank({"/api/subscriptions": subs})
    out = asyncio.run(run_tool("cancel_subscription", {"merchant": "云存储"}, bank))
    assert out["ok"] and bank.calls[-1][1] == "/api/subscriptions/s003/cancel"
    out = asyncio.run(run_tool("cancel_subscription", {"merchant": "不存在"},
                               DictBank({"/api/subscriptions": subs})))
    assert not out["ok"] and out["error"]["code"] == "SUBSCRIPTION_NOT_FOUND"


# ── 图级 E2E：LLM 链路与降级链路（离线：FakeLLM + DictBank）─────
def _graph_chat(text, sid, fake, bank):
    from app.graph.agent_graph import init_checkpointer
    from app.session.manager import manager
    llm.set_backend(fake)
    g.set_client_factory(lambda: bank)

    async def _run():
        await init_checkpointer()
        return await manager.handle_message(sid, text)
    return asyncio.run(_run())


def _final_text(out):
    return next(m["payload"]["text"] for m in out["messages"] if m["type"] == "final")


def test_graph_llm_chain_end_to_end():
    fake = FakeLLM(
        intent={"scenario": "billing", "goal": "分析上月账单", "confidence": 0.92,
                "slots": {"kind": "category", "period": "2026-08"}, "ambiguous": False},
        plan={"goal": "账单分析", "nodes": [{"id": "n1", "tool": "analyze_billing",
              "args": {"kind": "category", "period": "2026-08"}, "depends_on": []}]},
        reply="您上月餐饮支出 1240 元，是最大的一类。")
    bank = DictBank({"/api/billing/category-stats": {
        "code": "OK", "period": "2026-08", "items": [{"category": "餐饮", "amount": 1240.0}]}})
    out = _graph_chat("帮我看看上个月账单", "t_llm_e2e", fake, bank)
    assert _final_text(out) == "您上月餐饮支出 1240 元，是最大的一类。"   # LLM 回复过 verifier
    assert any(c[1] == "/api/billing/category-stats" for c in bank.calls)
    prompts = [u for _, u in fake.calls]
    assert any("分析用户最新一条消息" in p for p in prompts)          # 意图 prompt
    assert any("生成子任务 DAG" in p for p in prompts)                # 规划 prompt
    assert any("<untrusted_data>" in p for p in prompts)              # 回复前包裹（doc 02 §9.1）


def test_graph_llm_hallucinated_reply_falls_back_to_template():
    fake = FakeLLM(
        intent={"scenario": "query_balance", "goal": "查余额", "slots": {},
                "ambiguous": False, "confidence": 0.95},
        plan={"goal": "查余额", "nodes": [{"id": "n1", "tool": "query_balance", "args": {}}]},
        reply="您的余额是 999999 元，随便花。")                        # 数字幻觉
    bank = DictBank({"/api/accounts": {"items": [{"type": "checking", "balance": 1000.0}]}})
    out = _graph_chat("查一下余额", "t_llm_halluc", fake, bank)
    final = _final_text(out)
    assert "1,000.00" in final and "999999" not in final              # 回退模板渲染


def test_graph_llm_down_falls_back_to_rule_chain():
    fake = FakeLLM(intent=None, plan=None, reply=None)                # 全路超时/无效
    bank = DictBank({"/api/accounts": {"items": [{"type": "checking", "balance": 1000.0}]}})
    out = _graph_chat("查询余额", "t_llm_down", fake, bank)
    assert "1,000.00" in _final_text(out)                             # 规则意图+静态DAG+模板回复


