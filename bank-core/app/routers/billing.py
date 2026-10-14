"""账单分析 API（doc 02 §4.2）：分类统计 / 异常交易识别 / 月度报告（analyze_billing 落点）。

异常识别规则（doc 02 §4.2：3σ / 非常用时段 / 非常用对手方，按演示数据可调实现）：
  A 金额显著高于日常：单笔 ≥ 同类近 12 个月均值 ×3 且 ≥ ¥1000（避免房租等固定大额误报）；
  B 非常用时段：00:00-05:59 交易；
  C 陌生对手方：该对手方历史首次交易（全量流水仅出现 1 次）。
"""
import calendar
import statistics
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Subscription, Transaction
from .accounts import current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])

AMOUNT_FLOOR = 1000.0      # 规则 A 金额下限（防小额类目噪声）
AMOUNT_TIMES = 3.0         # 规则 A 倍数（同类均值 ×3 ≈ 3σ 稳健替代）
NIGHT_HOURS = range(0, 6)  # 规则 B 非常用时段


def _period_range(period: str | None) -> tuple[str, str, str]:
    """period：'YYYY-MM'（月）或 'YYYY'（年），缺省当月 → (起, 止, 标签)。"""
    import re
    p = (period or "").strip() or datetime.now().strftime("%Y-%m")
    if re.fullmatch(r"\d{4}", p):
        return f"{p}-01-01", f"{p}-12-31", p
    m2 = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m2 and 1 <= int(m2.group(2)) <= 12:
        y, m = int(m2.group(1)), int(m2.group(2))
        return f"{p}-01", f"{p}-{calendar.monthrange(y, m)[1]:02d}", p
    raise HTTPException(status_code=400, detail={"code": "BAD_PERIOD",
                                                 "message": "period 需为 YYYY-MM 或 YYYY"})


def _prev_month(period: str) -> str | None:
    if len(period) != 7:
        return None
    y, m = int(period[:4]), int(period[5:7])
    return f"{y}-{m - 1:02d}" if m > 1 else f"{y - 1}-12"


def _account_ids(db: Session, user_id: str) -> list[str]:
    return [a.id for a in db.query(Account).filter(Account.user_id == user_id).all()]


def _txns(db: Session, account_ids: list[str], start: str, end: str,
          expense_only: bool = False) -> list[Transaction]:
    q = db.query(Transaction).filter(
        Transaction.account_id.in_(account_ids),
        Transaction.created_at >= start, Transaction.created_at <= end + " 23:59:59",
        Transaction.status == "success")
    if expense_only:
        q = q.filter(Transaction.amount < 0)
    return q.all()


@router.get("/category-stats")
def category_stats(period: str | None = None, user_id: str = Depends(current_user),
                   db: Session = Depends(get_db)) -> dict:
    """消费分类统计：支出按类别聚合（金额/笔数/占比）+ 收入合计。"""
    start, end, label = _period_range(period)
    txns = _txns(db, _account_ids(db, user_id), start, end)
    by_cat: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "count": 0})
    income = 0.0
    for t in txns:
        if t.amount < 0:
            slot = by_cat[t.category]
            slot["amount"] += -t.amount
            slot["count"] += 1
        else:
            income += t.amount
    total_expense = round(sum(v["amount"] for v in by_cat.values()), 2)
    items = [dict(category=cat, amount=round(v["amount"], 2), count=v["count"],
                  ratio=round(v["amount"] / total_expense, 4) if total_expense else 0.0)
             for cat, v in sorted(by_cat.items(), key=lambda kv: -kv[1]["amount"])]
    return dict(period=label, items=items, total_expense=total_expense,
                income=round(income, 2), currency="CNY")


@router.get("/anomalies")
def anomalies(period: str | None = None, user_id: str = Depends(current_user),
              db: Session = Depends(get_db)) -> dict:
    """异常交易识别：规则 A/B/C 命中任一即标出，附命中依据（前端高亮卡片数据源）。"""
    start, end, label = _period_range(period)
    account_ids = _account_ids(db, user_id)
    txns = _txns(db, account_ids, start, end, expense_only=True)

    # 基线：近 12 个月（相对 period 起点）同类均值 + 对手方出现次数（含本期）
    base_start = f"{int(start[:4]) - 1}-{start[5:7]}-01"
    history = _txns(db, account_ids, base_start, end, expense_only=True)
    cat_amounts: dict[str, list[float]] = defaultdict(list)
    cp_count: dict[str, int] = defaultdict(int)
    for t in history:
        cat_amounts[t.category].append(-t.amount)
        cp_count[t.counterparty] += 1

    items = []
    for t in txns:
        amt = -t.amount
        reasons: list[str] = []
        peers = cat_amounts.get(t.category, [])
        if len(peers) >= 3:
            avg = statistics.fmean(peers)
            if avg > 0 and amt >= avg * AMOUNT_TIMES and amt >= AMOUNT_FLOOR:
                reasons.append(f"金额显著高于日常（同类均值 ¥{avg:,.2f} 的 {amt / avg:.1f} 倍）")
        if int(t.created_at[11:13]) in NIGHT_HOURS:
            reasons.append(f"非常用时段（凌晨 {t.created_at[11:16]}）")
        if cp_count.get(t.counterparty, 0) <= 1:
            reasons.append("陌生对手方（历史首次交易）")
        if reasons:
            items.append(dict(transaction_id=t.id, amount=round(amt, 2), category=t.category,
                              counterparty=t.counterparty, remark=t.remark,
                              created_at=t.created_at, reasons=reasons))
    items.sort(key=lambda x: -x["amount"])
    return dict(period=label, items=items, total=len(items),
                rules=["amount>=3x_category_avg", "night_00_06", "first_seen_counterparty"])


@router.get("/report")
def report(period: str | None = None, user_id: str = Depends(current_user),
           db: Session = Depends(get_db)) -> dict:
    """月度/年度账单报告聚合：收支净额、Top3 分类、异常数、订阅月成本、环比。"""
    start, end, label = _period_range(period)
    stats = category_stats(period, user_id, db)
    ano = anomalies(period, user_id, db)
    subs = db.query(Subscription).filter(Subscription.user_id == user_id,
                                         Subscription.status == "生效").all()
    sub_monthly = round(sum(s.amount if s.cycle == "月" else s.amount / 3 for s in subs), 2)
    mom = None
    prev = _prev_month(label)
    if prev:
        prev_stats = category_stats(prev, user_id, db)
        if prev_stats["total_expense"] > 0:
            change = (stats["total_expense"] - prev_stats["total_expense"]) / prev_stats["total_expense"]
            mom = dict(prev_period=prev, prev_expense=prev_stats["total_expense"],
                       change_pct=round(change * 100, 1))
    return dict(period=label, income=stats["income"], expense=stats["total_expense"],
                net=round(stats["income"] - stats["total_expense"], 2),
                top_categories=stats["items"][:3], anomaly_count=ano["total"],
                subscription_monthly=sub_monthly, mom=mom)