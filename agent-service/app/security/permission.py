"""权限分级引擎（doc 02 §8.1/§8.2）：静态注册表 + 5 条动态规则，只能升不能降，独立于 LLM。

规则（doc 02 §8.2 + §9.4）：
  0 拒绝优先·熔断：写操作禁用中（breaker T1 open）→ deny，提示人工接管
  1 当日累计转账 ≤¥1000 黄 / >¥1000 红   2 陌生收款人升一级   3 高频写操作升一级
  4 单笔 >¥50000 拒绝                    5 凌晨 1-5 点大额（≥¥2000）自动升红（T4）
"""
from dataclasses import dataclass, field
from datetime import datetime

from .breaker import NIGHT_LARGE_LIMIT, night_risk
from ..tools.specs import GREEN, RED, WRITE_TOOLS, spec

DAILY_LIMIT = 1000.0     # 当日累计转账 > ¥1000 → 升红（doc 02 §8.2）
SINGLE_LIMIT = 50000.0   # 单笔 > ¥50000 → 拒绝，提示转人工/网点
FREQ_WINDOW_SEC = 60
FREQ_LIMIT = 3           # 1 分钟内 ≥3 次写操作 → 升一级并触发熔断评估

_ORDER = [GREEN, "yellow", RED]


def _current_hour() -> int:
    """当前小时（规则 5 数据源；测试可 monkeypatch）。"""
    return datetime.now().hour


def _up(level: str, steps: int = 1) -> str:
    return _ORDER[min(_ORDER.index(level) + steps, len(_ORDER) - 1)]


@dataclass
class Decision:
    tool: str
    level: str                    # green / yellow / red / deny
    reasons: list[str] = field(default_factory=list)
    code: str = ""                # 下行错误码（deny 时；空 → executor 用默认 LIMIT_EXCEEDED）

    @property
    def needs_confirm(self) -> bool:
        return self.level in ("yellow", RED)

    @property
    def needs_mfa(self) -> bool:
        return self.level == RED

    @property
    def denied(self) -> bool:
        return self.level == "deny"

    def __str__(self) -> str:
        return f"[{self.level}] {self.tool}｜依据：" + "；".join(self.reasons)


def decide(tool: str, args: dict | None = None, ctx: dict | None = None) -> Decision:
    """裁决顺序：熔断禁写 → 静态定级 → 动态升级（拒/累计/陌生/高频/凌晨大额，只能升）。

    ctx 约定：today_transfer_total(float) / contact_known(bool|None) /
              recent_writes_60s(int) / write_disabled(bool) / hour(int，缺省取当前时间)
    """
    s = spec(tool)
    level, reasons = s.base_risk, [f"静态定级 {s.base_risk}"]
    a, c = args or {}, ctx or {}
    amount = float(a.get("amount") or a.get("total_amount") or a.get("budget") or 0.0)

    # 规则 0（拒绝优先·熔断 T1）：写操作禁用中 → 拒绝，仅查询可用，提示人工接管
    if c.get("write_disabled") and tool in WRITE_TOOLS:
        return Decision(tool, "deny", ["熔断：连续失败已暂停写操作（仅允许查询），"
                                       "提示人工接管"], code="RISK_DENIED")

    # 规则 4（拒绝优先）：单笔 > 5 万 → 拒绝并提示转人工/网点
    if amount > SINGLE_LIMIT:
        return Decision(tool, "deny", [f"单笔 ¥{amount:,.2f} > ¥{SINGLE_LIMIT:,.0f} → 拒绝并提示转人工/网点"],
                        code="LIMIT_EXCEEDED")

    # 规则 1：当日累计转账——≤¥1000 黄；>¥1000 红（实时查 transactions 聚合，由调用方传入）
    if tool in ("transfer", "aa_split"):
        today = float(c.get("today_transfer_total") or 0.0) + amount
        if today > DAILY_LIMIT:
            if level != RED:
                reasons.append(f"当日累计转账 ¥{today:,.2f} 超 ¥{DAILY_LIMIT:,.0f} 阈值 → 升红（需 MFA）")
            level = RED
        else:
            reasons.append(f"当日累计转账 ¥{today:,.2f} ≤ ¥{DAILY_LIMIT:,.0f} → 维持黄")

    # 规则 2：陌生收款人（不在通讯录/首次交易）→ 升一级
    if c.get("contact_known") is False and level != RED:
        level = _up(level)
        reasons.append("收款人不在通讯录/首次交易 → 升一级")

    # 规则 3：高频写操作（1 分钟 ≥3 次）→ 升一级并触发熔断评估
    if tool in WRITE_TOOLS and int(c.get("recent_writes_60s") or 0) >= FREQ_LIMIT and level != RED:
        level = _up(level)
        reasons.append(f"1 分钟内已 {c.get('recent_writes_60s')} 次写操作（≥{FREQ_LIMIT}）→ 升一级并触发熔断评估")

    # 规则 5（熔断 T4）：凌晨 1-5 点大额写操作 → 自动升红 + 二次确认（doc 02 §9.4）；
    # 无论此前级别如何都记录凌晨依据（审计可追溯 T4 触发）
    hour = int(c["hour"]) if c.get("hour") is not None else _current_hour()
    if night_risk(hour, amount, tool in WRITE_TOOLS) and level != "deny":
        level = RED
        reasons.append(f"凌晨 {hour:02d} 点大额 ¥{amount:,.2f}（≥¥{NIGHT_LARGE_LIMIT:,.0f}）"
                       f"→ 自动升红 + 二次确认（熔断 T4）")

    return Decision(tool, level, reasons)

