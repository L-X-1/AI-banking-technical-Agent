"""M1 DoD #4：权限引擎静态 + 动态定级单测（doc 02 §8.2；doc 05 M1#4）。"""
from app.security.permission import FREQ_LIMIT, decide
from app.tools.specs import GREEN, RED, TOOL_SPECS, YELLOW

EXPECTED_TOOLS = {
    "query_balance", "query_transactions", "resolve_contact", "change_password",
    "transfer", "aa_split", "analyze_billing", "detect_subscriptions",
    "query_wealth_products", "query_holdings", "recommend_wealth", "purchase_wealth", "redeem_wealth",
    "apply_virtual_card", "adjust_card_limit", "freeze_card", "unfreeze_card",
    "report_card_loss", "cancel_card_loss", "cancel_subscription",
    "freeze_funds", "unfreeze_funds", "create_scheduled_task", "place_gift_order",
}


def test_registry_matches_doc02_tool_list():
    assert len(TOOL_SPECS) == 24, "doc 02 §5：7 模块 24 工具"
    assert set(TOOL_SPECS) == EXPECTED_TOOLS


def test_static_levels():
    assert decide("query_balance").level == GREEN
    assert decide("query_transactions").level == GREEN
    assert decide("resolve_contact").level == GREEN
    assert decide("analyze_billing").level == GREEN
    assert decide("detect_subscriptions").level == GREEN
    assert decide("recommend_wealth").level == GREEN
    assert decide("freeze_card").level == YELLOW
    assert decide("adjust_card_limit").level == YELLOW
    assert decide("cancel_subscription").level == YELLOW
    assert decide("apply_virtual_card").level == YELLOW
    assert decide("freeze_funds").level == YELLOW
    assert decide("create_scheduled_task").level == YELLOW
    assert decide("place_gift_order").level == YELLOW
    assert decide("purchase_wealth").level == RED
    assert decide("redeem_wealth").level == RED
    assert decide("report_card_loss").level == RED
    assert decide("cancel_card_loss").level == RED
    assert decide("change_password").level == RED


def test_transfer_within_daily_limit_is_yellow():
    d = decide("transfer", {"amount": 200}, {"today_transfer_total": 0})
    assert d.level == YELLOW
    assert d.needs_confirm and not d.needs_mfa


def test_transfer_daily_accumulation_upgrades_to_red():
    d = decide("transfer", {"amount": 500}, {"today_transfer_total": 600})
    assert d.level == RED and d.needs_mfa
    assert any("当日累计" in r for r in d.reasons)


def test_transfer_at_threshold_boundary_stays_yellow():
    d = decide("transfer", {"amount": 400}, {"today_transfer_total": 600})   # 恰好 1000
    assert d.level == YELLOW


def test_stranger_contact_upgrades_one_level():
    d = decide("transfer", {"amount": 200}, {"contact_known": False})
    assert d.level == RED and any("陌生收款人" in r or "通讯录" in r for r in d.reasons)
    d2 = decide("aa_split", {"total_amount": 300}, {"contact_known": False})
    assert d2.level == RED


def test_known_contact_keeps_base_level():
    d = decide("transfer", {"amount": 200}, {"contact_known": True, "today_transfer_total": 0})
    assert d.level == YELLOW


def test_single_limit_deny():
    d = decide("transfer", {"amount": 50001})
    assert d.level == "deny" and d.denied and not d.needs_confirm


def test_high_frequency_upgrades():
    d = decide("freeze_card", {}, {"recent_writes_60s": FREQ_LIMIT})
    assert d.level == RED and any("写操作" in r for r in d.reasons)


def test_only_upgrade_never_downgrade():
    d = decide("purchase_wealth", {"amount": 10000}, {"contact_known": False, "recent_writes_60s": 5})
    assert d.level == RED, "红级不得被动态规则降级"


def test_decision_reasons_are_auditable():
    d = decide("transfer", {"amount": 500}, {"today_transfer_total": 600})
    assert d.reasons and all(isinstance(r, str) for r in d.reasons)
    assert "静态定级" in d.reasons[0]
