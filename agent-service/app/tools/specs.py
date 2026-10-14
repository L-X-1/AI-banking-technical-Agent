"""24 个工具的服务端注册表（doc 02 §5 为唯一清单）。

铁律：risk 定义在服务端；Planner/LLM 输出中的 risk 仅作参考，不作裁决依据（doc 02 §8.3）。
"""
from dataclasses import dataclass

GREEN, YELLOW, RED = "green", "yellow", "red"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    base_risk: str
    group: str          # A 资金 / B 洞察 / C 管理 / D 联动 / 支撑
    bank: str           # bank-core API 映射（doc 02 §4）
    dynamic: bool = False   # 参与动态升级（金额/收款人/频率）


TOOL_SPECS: dict[str, ToolSpec] = {s.name: s for s in [
    # 通用 / 支撑
    ToolSpec("query_balance", GREEN, "支撑", "GET /api/accounts"),
    ToolSpec("query_transactions", GREEN, "支撑", "GET /api/accounts/{id}/transactions"),
    ToolSpec("resolve_contact", GREEN, "支撑", "GET /api/contacts?keyword="),
    ToolSpec("change_password", RED, "支撑", "POST /api/auth/change-password"),
    # A 转账
    ToolSpec("transfer", YELLOW, "A", "POST /api/transfers", dynamic=True),
    ToolSpec("aa_split", YELLOW, "A", "POST /api/transfers/aa-split", dynamic=True),
    # B 账单 / 订阅识别
    ToolSpec("analyze_billing", GREEN, "B", "GET /api/billing/category-stats|anomalies|report"),
    ToolSpec("detect_subscriptions", GREEN, "B", "GET /api/subscriptions/detect"),
    # A 理财
    ToolSpec("query_wealth_products", GREEN, "A", "GET /api/wealth/products"),
    ToolSpec("query_holdings", GREEN, "A", "GET /api/wealth/holdings"),
    ToolSpec("recommend_wealth", GREEN, "A", "GET /api/wealth/products?risk_max="),
    ToolSpec("purchase_wealth", RED, "A", "POST /api/wealth/purchase"),
    ToolSpec("redeem_wealth", RED, "A", "POST /api/wealth/redeem"),
    # C 卡片
    ToolSpec("apply_virtual_card", YELLOW, "C", "POST /api/cards/apply-virtual"),
    ToolSpec("adjust_card_limit", YELLOW, "C", "POST /api/cards/{id}/limit"),
    ToolSpec("freeze_card", YELLOW, "C", "POST /api/cards/{id}/freeze"),
    ToolSpec("unfreeze_card", YELLOW, "C", "POST /api/cards/{id}/unfreeze"),
    ToolSpec("report_card_loss", RED, "C", "POST /api/cards/{id}/report-loss"),
    ToolSpec("cancel_card_loss", RED, "C", "POST /api/cards/{id}/cancel-loss"),
    # C 订阅管理
    ToolSpec("cancel_subscription", YELLOW, "C", "POST /api/subscriptions/{id}/cancel"),
    # D 联动
    ToolSpec("freeze_funds", YELLOW, "D", "POST /api/accounts/{id}/freeze-amount"),
    ToolSpec("unfreeze_funds", YELLOW, "D", "POST /api/accounts/{id}/unfreeze-amount"),
    ToolSpec("create_scheduled_task", YELLOW, "D", "POST /api/scheduled-tasks"),
    ToolSpec("place_gift_order", YELLOW, "D", "POST /api/scheduled-tasks (gift_order)"),
]}

WRITE_TOOLS = {name for name, s in TOOL_SPECS.items() if s.base_risk != GREEN}


def spec(name: str) -> ToolSpec:
    if name not in TOOL_SPECS:
        raise KeyError(f"工具未注册：{name}（doc 02 §5 为唯一清单）")
    return TOOL_SPECS[name]