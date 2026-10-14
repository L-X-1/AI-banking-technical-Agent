"""工具执行器：DAG 节点 → bank-core API（doc 02 §4/§5 映射；24 工具 M3 全量落地）。

M3 Step 2：实体解析下沉——Planner（LLM 或规则）只需给出业务标识
（card_tail / product_name / merchant / holding 名称），执行器先查列表再定位唯一实体：
唯一匹配 → 解析为 ID；多候选 → *_AMBIGUOUS；无匹配 → *_NOT_FOUND（先查后写，doc 03 §3.3 规则 2）。
"""
from typing import Any

from .bank_client import BankClient, BankError
from .specs import spec


async def _resolve_card_id(args: dict, client: BankClient) -> str:
    if args.get("card_id"):
        return str(args["card_id"])
    tail = "".join(ch for ch in str(args.get("card_tail") or "") if ch.isdigit())[-4:]
    data = await client.get("/api/cards")
    items = data.get("items") or []
    hits = [c for c in items if tail and tail in str(c.get("card_no_masked") or "")]
    if not hits and not tail and len(items) == 1:
        hits = items
    if len(hits) == 1:
        return hits[0]["id"]
    if hits:
        raise BankError("CARD_AMBIGUOUS", f"尾号 {tail} 匹配到 {len(hits)} 张卡，请提供更完整卡号", 409)
    raise BankError("CARD_NOT_FOUND", f"没有找到尾号 {tail or '—'} 的卡片", 404)


async def _resolve_product_id(args: dict, client: BankClient) -> str:
    if args.get("product_id"):
        return str(args["product_id"])
    name = str(args.get("product_name") or "").strip()
    data = await client.get("/api/wealth/products")
    items = data.get("items") or []
    exact = [p for p in items if p.get("name") == name]
    hits = exact or [p for p in items if name and name in str(p.get("name") or "")]
    if len(hits) == 1:
        return hits[0]["id"]
    if hits:
        names = "、".join(str(p.get("name")) for p in hits[:4])
        raise BankError("PRODUCT_AMBIGUOUS", f"“{name}”匹配到 {len(hits)} 只产品（{names}），请指明确切名称", 409)
    raise BankError("PRODUCT_NOT_FOUND", f"没有找到名称含“{name or '—'}”的理财产品", 404)


async def _resolve_holding_id(args: dict, client: BankClient) -> str:
    if args.get("holding_id"):
        return str(args["holding_id"])
    name = str(args.get("product_name") or "").strip()
    data = await client.get("/api/wealth/holdings")
    items = data.get("items") or []
    hits = [h for h in items if name and name in str(h.get("product_name") or h.get("name") or "")]
    if len(hits) == 1:
        return hits[0]["id"]
    if hits:
        raise BankError("HOLDING_AMBIGUOUS", f"“{name}”匹配到 {len(hits)} 笔持仓，请指明具体产品", 409)
    raise BankError("HOLDING_NOT_FOUND", f"没有名称含“{name or '—'}”的持仓", 404)


async def _resolve_subscription_id(args: dict, client: BankClient) -> str:
    if args.get("subscription_id"):
        return str(args["subscription_id"])
    merchant = str(args.get("merchant") or "").strip()
    data = await client.get("/api/subscriptions")
    # bank 订阅状态为中文「生效/已取消」（原 "active" 过滤恒空 → NOT_FOUND，M3#3 阻断）；
    # 不按状态过滤：重复取消由 bank cancel 的 changed=false 幂等承接（transcript 可重放）。
    items = data.get("items") or []
    hits = [s for s in items if merchant and merchant in str(s.get("merchant") or "")]
    if len(hits) == 1:
        return hits[0]["id"]
    if hits:
        raise BankError("SUBSCRIPTION_AMBIGUOUS", f"“{merchant}”匹配到 {len(hits)} 个订阅，请指明商户", 409)
    raise BankError("SUBSCRIPTION_NOT_FOUND", f"没有找到“{merchant or '—'}”的在订服务", 404)


async def run_tool(name: str, args: dict[str, Any], client: BankClient) -> dict[str, Any]:
    """统一返回 {"ok": bool, "data"|"error"}，供 reflector 判定。"""
    spec(name)  # 未注册工具 → KeyError（编程错误，直接暴露）
    try:
        data = await _dispatch(name, args, client)
        return {"ok": True, "data": data}
    except BankError as e:
        return {"ok": False, "error": {"code": e.code, "message": e.message}}
    except NotImplementedError as e:
        return {"ok": False, "error": {"code": "TOOL_NOT_IN_M1", "message": str(e)}}


async def _dispatch(name: str, args: dict[str, Any], client: BankClient) -> dict:
    if name == "resolve_contact":
        return await client.get("/api/contacts", keyword=args.get("keyword") or "")
    if name == "query_balance":
        return await client.get("/api/accounts")
    if name == "query_transactions":
        return await client.get(
            f"/api/accounts/{args.get('account_id') or 'a001'}/transactions",
            category=args.get("category"), keyword=args.get("keyword"),
            **{"from": args.get("from_"), "to": args.get("to")},
            page=args.get("page"), page_size=args.get("page_size") or 20)
    if name == "transfer":
        payload = {k: args[k] for k in ("to_contact_id", "amount", "remark", "schedule_time") if args.get(k) is not None}
        return await client.post("/api/transfers", payload, idempotency_key=args.get("idempotency_key"))
    if name == "aa_split":
        contact_ids = args.get("contact_ids")
        if not contact_ids:
            # 规则 plan 只给 keyword + member_count（如「我们仨」→ 2）：执行器内查通讯录并
            # 截取前 N 位——绕开 resolve_contact 多候选消歧中断，保证 N 人 AA → N-1 笔（doc 05 M3#5）。
            found = await client.get("/api/contacts", keyword=str(args.get("keyword") or "同事"))
            n = max(1, int(args.get("member_count") or 2))
            contact_ids = [c["id"] for c in (found.get("items") or [])[:n]]
        payload = {k: args[k] for k in ("total_amount", "remark") if args.get(k) is not None}
        payload["contact_ids"] = contact_ids
        return await client.post("/api/transfers/aa-split", payload, idempotency_key=args.get("idempotency_key"))
    # ── B 账单 / 订阅识别（M3）─────────────────────────────────
    if name == "analyze_billing":
        kind = {"category": "category-stats", "stats": "category-stats", "anomaly": "anomalies",
                "anomalies": "anomalies", "report": "report"}.get(str(args.get("kind") or "category"), "category-stats")
        return await client.get(f"/api/billing/{kind}", period=args.get("period"))
    if name == "detect_subscriptions":
        return await client.get("/api/subscriptions/detect")
    if name == "cancel_subscription":
        sub_id = await _resolve_subscription_id(args, client)
        return await client.post(f"/api/subscriptions/{sub_id}/cancel", {})
    # ── A 理财（M3）───────────────────────────────────────────
    if name == "query_wealth_products":
        return await client.get("/api/wealth/products", risk_max=args.get("risk_max"), type=args.get("type"))
    if name == "recommend_wealth":
        data = await client.get("/api/wealth/products", risk_max=args.get("risk_max"))
        items = sorted(data.get("items", []), key=lambda x: (-x["annual_yield"], x["risk_level"]))[:5]
        return {**data, "items": items, "total": len(items), "recommend": True}
    if name == "query_holdings":
        return await client.get("/api/wealth/holdings")
    if name == "purchase_wealth":
        product_id = await _resolve_product_id(args, client)
        payload = {"product_id": product_id, "amount": args["amount"]}
        return await client.post("/api/wealth/purchase", payload, idempotency_key=args.get("idempotency_key"))
    if name == "redeem_wealth":
        holding_id = await _resolve_holding_id(args, client)
        payload = {"holding_id": holding_id, "amount": args["amount"]}
        return await client.post("/api/wealth/redeem", payload, idempotency_key=args.get("idempotency_key"))
    # ── C 卡片（M3）───────────────────────────────────────────
    if name == "apply_virtual_card":
        return await client.post("/api/cards/apply-virtual", {})
    if name == "adjust_card_limit":
        card_id = await _resolve_card_id(args, client)
        return await client.post(f"/api/cards/{card_id}/limit", {"daily_limit": args["daily_limit"]})
    if name in ("freeze_card", "unfreeze_card", "report_card_loss", "cancel_card_loss"):
        card_id = await _resolve_card_id(args, client)
        action = {"freeze_card": "freeze", "unfreeze_card": "unfreeze",
                  "report_card_loss": "report-loss", "cancel_card_loss": "cancel-loss"}[name]
        return await client.post(f"/api/cards/{card_id}/{action}", {})
    # ── D 联动（M3）───────────────────────────────────────────
    if name in ("freeze_funds", "unfreeze_funds"):
        account_id = args.get("account_id") or "a001"
        action = "freeze-amount" if name == "freeze_funds" else "unfreeze-amount"
        payload = {k: args[k] for k in ("amount", "reason") if args.get(k) is not None}
        return await client.post(f"/api/accounts/{account_id}/{action}", payload)
    if name == "create_scheduled_task":
        task_type = args.get("task_type") or args.get("type")
        payload = args.get("payload") or {k: v for k, v in args.items()
                                          if k not in ("task_type", "type", "next_run_at", "run_at",
                                                       "recurrence", "idempotency_key", "payload")}
        body = {"task_type": task_type, "payload": payload,
                "next_run_at": args.get("next_run_at") or args.get("run_at"),
                "recurrence": args.get("recurrence")}
        return await client.post("/api/scheduled-tasks", {k: v for k, v in body.items() if v is not None})
    if name == "place_gift_order":
        payload = {"items": args.get("items"), "amount": args.get("amount") or args.get("budget"),
                   "recipient": args.get("recipient"), "merchant": args.get("merchant")}
        body = {"task_type": "gift_order", "payload": {k: v for k, v in payload.items() if v is not None},
                "next_run_at": args.get("next_run_at") or args.get("run_at")}
        return await client.post("/api/scheduled-tasks", body)
    # ── 支撑（M3 补落点）──────────────────────────────────────
    if name == "change_password":
        payload = {"old_password": args["old_password"], "new_password": args["new_password"]}
        return await client.post("/api/auth/change-password", payload,
                                 idempotency_key=args.get("idempotency_key"))
    raise NotImplementedError(f"{name} 的 bank-core API 属 M3 落地（doc 02 映射：{spec(name).bank}）")


async def today_transfer_total(client: BankClient, account_id: str = "a001") -> float:
    """当日累计转账（负数求和取绝对值）——权限引擎规则 1 的数据源（doc 02 §8.2）。"""
    from datetime import date

    today = date.today().isoformat()
    data = await client.get(f"/api/accounts/{account_id}/transactions",
                            **{"from": today, "to": today}, category="转账", page_size=100)
    total = sum(-t["amount"] for t in data.get("items", []) if t["amount"] < 0 and t["status"] == "success")
    return round(total, 2)
