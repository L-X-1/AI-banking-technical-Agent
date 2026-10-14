"""订阅识别与管理 API（doc 02 §4.5）：列表 / 流水自动识别候选 / 一键取消。

detect 规则：近 12 个月「订阅」类流水按商户归并——同商户 ≥3 笔且金额稳定（极差 ≤¥1）
判定为周期性扣费；与 subscriptions 表比对，未登记者标 is_new=true（"遗忘订阅"演示）。
"""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Subscription, Transaction
from .accounts import current_user
from .transfers import _err

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])

MIN_OCCURRENCES = 3
AMOUNT_TOLERANCE = 1.0


def _sub_dict(s: Subscription) -> dict:
    return dict(id=s.id, merchant=s.merchant, amount=s.amount, cycle=s.cycle,
                next_billing_date=s.next_billing_date, status=s.status)


@router.get("")
def list_subscriptions(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Subscription).filter(Subscription.user_id == user_id).order_by(Subscription.id).all()
    items = [_sub_dict(s) for s in rows]
    monthly = round(sum(s.amount if s.cycle == "月" else s.amount / 3
                        for s in rows if s.status == "生效"), 2)
    return dict(items=items, total=len(items), monthly_cost=monthly)


@router.get("/detect")
def detect(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """从流水归并周期性扣费，输出候选订阅（含已在册匹配与 is_new 候选）。"""
    since = (datetime.now() - timedelta(days=370)).strftime("%Y-%m-%d")
    account_ids = [a.id for a in db.query(Account).filter(Account.user_id == user_id).all()]
    txns = db.query(Transaction).filter(
        Transaction.account_id.in_(account_ids),
        Transaction.category == "订阅", Transaction.amount < 0,
        Transaction.status == "success", Transaction.created_at >= since).all()
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_merchant[t.counterparty].append(t)

    registered = {s.merchant: s for s in
                  db.query(Subscription).filter(Subscription.user_id == user_id).all()}
    items = []
    for merchant, rows in sorted(by_merchant.items()):
        amounts = [-t.amount for t in rows]
        if len(rows) < MIN_OCCURRENCES or max(amounts) - min(amounts) > AMOUNT_TOLERANCE:
            continue
        rows.sort(key=lambda t: t.created_at)
        sub = registered.get(merchant)
        items.append(dict(
            merchant=merchant, amount=round(amounts[-1], 2), cycle="月",
            occurrences=len(rows),
            first_billing=rows[0].created_at[:10], last_billing=rows[-1].created_at[:10],
            yearly_cost=round(amounts[-1] * 12, 2),
            subscription_id=sub.id if sub else None,
            subscription_status=sub.status if sub else None,
            is_new=sub is None))
    items.sort(key=lambda x: -x["yearly_cost"])
    return dict(items=items, total=len(items),
                new_candidates=sum(1 for i in items if i["is_new"]))


@router.post("/{subscription_id}/cancel")
def cancel(subscription_id: str, user_id: str = Depends(current_user),
           db: Session = Depends(get_db)) -> dict:
    s = db.get(Subscription, subscription_id)
    if s is None or s.user_id != user_id:
        raise _err(404, "SUBSCRIPTION_NOT_FOUND", "订阅不存在")
    changed = s.status != "已取消"
    s.status = "已取消"
    db.commit()
    return dict(code="OK", changed=changed, saved_monthly=s.amount if changed else 0.0,
                **_sub_dict(s))
