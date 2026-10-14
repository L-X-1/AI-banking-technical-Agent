"""账户与交易流水 API（doc 02 §4.1）。"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Transaction

router = APIRouter(prefix="/api", tags=["accounts"])


def current_user(x_user_id: str = Header(default="u001")) -> str:
    """演示环境：X-User-Id 头标识客户，默认张三 u001。"""
    return x_user_id


def _txn_dict(t: Transaction) -> dict:
    return dict(id=t.id, amount=t.amount, category=t.category, counterparty=t.counterparty,
                remark=t.remark, channel=t.channel, status=t.status, created_at=t.created_at)


@router.get("/accounts")
def list_accounts(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Account).filter(Account.user_id == user_id).order_by(Account.id).all()
    return {"items": [dict(id=a.id, account_no=a.account_no, type=a.type, balance=round(a.balance, 2),
                           frozen_amount=round(a.frozen_amount, 2), currency=a.currency) for a in rows],
            "total": len(rows)}


@router.get("/accounts/{account_id}/transactions")
def list_transactions(account_id: str, from_: str | None = Query(default=None, alias="from"),
                      to: str | None = None, category: str | None = None, keyword: str | None = None,
                      page: int = 1, page_size: int = 20, db: Session = Depends(get_db)) -> dict:
    if db.get(Account, account_id) is None:
        raise HTTPException(status_code=404, detail={"code": "ACCOUNT_NOT_FOUND", "message": "账户不存在"})
    q = db.query(Transaction).filter(Transaction.account_id == account_id)
    if from_:
        q = q.filter(Transaction.created_at >= from_)
    if to:
        q = q.filter(Transaction.created_at <= to + " 23:59:59")
    if category:
        q = q.filter(Transaction.category == category)
    if keyword:
        q = q.filter(Transaction.counterparty.contains(keyword) | Transaction.remark.contains(keyword))
    total = q.count()
    items = q.order_by(Transaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_txn_dict(t) for t in items], "total": total, "page": page, "page_size": page_size}


# ── 活期资金锁定/解锁（跨场景联动，doc 02 §4.5；freeze_funds/unfreeze_funds 落点）──

class FreezeRequest(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    reason: str = Field(default="", max_length=100)


def _own_account(db: Session, account_id: str, user_id: str) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": "ACCOUNT_NOT_FOUND", "message": "账户不存在"})
    return account


def _account_state(a: Account) -> dict:
    return dict(account_id=a.id, balance=round(a.balance, 2), frozen_amount=round(a.frozen_amount, 2),
                available=round(a.balance - a.frozen_amount, 2))


@router.post("/accounts/{account_id}/freeze-amount")
def freeze_amount(account_id: str, req: FreezeRequest, user_id: str = Depends(current_user),
                  db: Session = Depends(get_db)) -> dict:
    account = _own_account(db, account_id, user_id)
    if account.balance - account.frozen_amount < req.amount:
        raise HTTPException(status_code=400, detail={"code": "INSUFFICIENT_AVAILABLE",
                                                     "message": "可用余额不足，无法锁定"})
    account.frozen_amount = round(account.frozen_amount + req.amount, 2)
    db.commit()
    return dict(code="OK", reason=req.reason, **_account_state(account))


@router.post("/accounts/{account_id}/unfreeze-amount")
def unfreeze_amount(account_id: str, req: FreezeRequest, user_id: str = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    account = _own_account(db, account_id, user_id)
    if account.frozen_amount < req.amount:
        raise HTTPException(status_code=400, detail={"code": "INSUFFICIENT_FROZEN",
                                                     "message": "锁定金额不足，无法解锁"})
    account.frozen_amount = round(account.frozen_amount - req.amount, 2)
    db.commit()
    return dict(code="OK", **_account_state(account))
