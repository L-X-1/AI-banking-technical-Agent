"""理财 API（doc 02 §4.3）：产品/持仓查询 + 申购/赎回（写操作强制 Idempotency-Key）。

申购硬校验（服务端，独立于 Agent）：用户风险等级 ≥ 产品风险等级；金额 ≥ 起购额；活期可用余额充足。
"""
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Transaction, User, WealthHolding, WealthProduct
from .accounts import current_user
from .transfers import _checking_account, _err, _next_id

router = APIRouter(prefix="/api/wealth", tags=["wealth"])


def _product_dict(p: WealthProduct) -> dict:
    return dict(id=p.id, code=p.code, name=p.name, type=p.type, risk_level=p.risk_level,
                annual_yield=p.annual_yield, min_amount=p.min_amount, lock_days=p.lock_days)


def _holding_dict(db: Session, h: WealthHolding) -> dict:
    p = db.get(WealthProduct, h.product_id)
    return dict(id=h.id, product_id=h.product_id, product_name=p.name if p else h.product_id,
                risk_level=p.risk_level if p else None,
                annual_yield=p.annual_yield if p else None,
                amount=round(h.amount, 2), profit=round(h.profit, 2),
                total=round(h.amount + h.profit, 2), status=h.status)


@router.get("/products")
def list_products(risk_max: int | None = None, type: str | None = None,
                  db: Session = Depends(get_db)) -> dict:
    q = db.query(WealthProduct)
    if risk_max is not None:
        q = q.filter(WealthProduct.risk_level <= risk_max)
    if type:
        q = q.filter(WealthProduct.type == type)
    rows = q.order_by(WealthProduct.risk_level, WealthProduct.id).all()
    return {"items": [_product_dict(p) for p in rows], "total": len(rows)}


@router.get("/products/{product_id}")
def product_detail(product_id: str, db: Session = Depends(get_db)) -> dict:
    p = db.get(WealthProduct, product_id)
    if p is None:
        raise _err(404, "PRODUCT_NOT_FOUND", "产品不存在")
    return _product_dict(p)


@router.get("/holdings")
def list_holdings(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(WealthHolding).filter(WealthHolding.user_id == user_id).order_by(WealthHolding.id).all()
    items = [_holding_dict(db, h) for h in rows]
    return dict(items=items, total=len(items),
                total_amount=round(sum(i["amount"] for i in items), 2),
                total_profit=round(sum(i["profit"] for i in items), 2))


class PurchaseRequest(BaseModel):
    product_id: str
    amount: float = Field(gt=0, le=10_000_000)


class RedeemRequest(BaseModel):
    holding_id: str
    amount: float = Field(gt=0, le=10_000_000)


def _replay(db: Session, key: str) -> dict | None:
    txn = db.query(Transaction).filter(Transaction.idempotency_key == key).first()
    if txn is None:
        return None
    return dict(code="IDEMPOTENT_REPLAY", transaction_id=txn.id, amount=abs(txn.amount),
                counterparty=txn.counterparty, executed_at=txn.created_at)


@router.post("/purchase")
def purchase(req: PurchaseRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
             user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not idempotency_key:
        raise _err(400, "MISSING_IDEMPOTENCY_KEY", "写操作必须携带 Idempotency-Key 头")
    if (hit := _replay(db, idempotency_key)) is not None:
        return hit
    user = db.get(User, user_id)
    product = db.get(WealthProduct, req.product_id)
    if product is None:
        raise _err(404, "PRODUCT_NOT_FOUND", "产品不存在")
    if user.risk_level < product.risk_level:
        raise _err(403, "RISK_LEVEL_EXCEEDED",
                   f"产品风险等级 R{product.risk_level} 超出您的风险承受等级 R{user.risk_level}，已拒绝申购")
    if req.amount < product.min_amount:
        raise _err(400, "BELOW_MIN_AMOUNT", f"低于起购金额 ¥{product.min_amount:,.0f}")
    account = _checking_account(db, user_id)
    if account.balance - account.frozen_amount < req.amount:
        raise _err(400, "INSUFFICIENT_BALANCE", "活期可用余额不足")

    account.balance = round(account.balance - req.amount, 2)
    holding = db.query(WealthHolding).filter(WealthHolding.user_id == user_id,
                                             WealthHolding.product_id == product.id,
                                             WealthHolding.status == "持有").first()
    if holding is None:
        holding = WealthHolding(id=_next_id(db, WealthHolding, "h", 3), user_id=user_id,
                                product_id=product.id, amount=0.0, profit=0.0, status="持有")
        db.add(holding)
    holding.amount = round(holding.amount + req.amount, 2)
    txn = Transaction(id=_next_id(db, Transaction, "t"), account_id=account.id,
                      amount=-round(req.amount, 2), category="理财", counterparty=product.name,
                      remark="申购", channel="agent", status="success",
                      idempotency_key=idempotency_key)
    db.add(txn)
    db.commit()
    return dict(code="OK", holding_id=holding.id, product_id=product.id, product_name=product.name,
                amount=req.amount, holding_amount=holding.amount,
                balance_after=round(account.balance, 2), transaction_id=txn.id)


@router.post("/redeem")
def redeem(req: RedeemRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
           user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """赎回：本金+按比例结算收益回到活期；部分赎回保留剩余持仓。"""
    if not idempotency_key:
        raise _err(400, "MISSING_IDEMPOTENCY_KEY", "写操作必须携带 Idempotency-Key 头")
    if (hit := _replay(db, idempotency_key)) is not None:
        return hit
    holding = db.get(WealthHolding, req.holding_id)
    if holding is None or holding.user_id != user_id:
        raise _err(404, "HOLDING_NOT_FOUND", "持仓不存在")
    if holding.status != "持有":
        raise _err(409, "HOLDING_NOT_ACTIVE", f"持仓状态为 {holding.status}，不可赎回")
    if req.amount > holding.amount:
        raise _err(400, "REDEEM_EXCEEDS_HOLDING", f"赎回金额超出持仓本金 ¥{holding.amount:,.2f}")

    profit_share = round(holding.profit * (req.amount / holding.amount), 2) if holding.amount else 0.0
    holding.amount = round(holding.amount - req.amount, 2)
    holding.profit = round(holding.profit - profit_share, 2)
    if holding.amount <= 0.004:
        holding.amount, holding.status = 0.0, "已赎回"
    payout = round(req.amount + profit_share, 2)
    account = _checking_account(db, user_id)
    account.balance = round(account.balance + payout, 2)
    product = db.get(WealthProduct, holding.product_id)
    txn = Transaction(id=_next_id(db, Transaction, "t"), account_id=account.id, amount=payout,
                      category="理财", counterparty=product.name if product else holding.product_id,
                      remark=f"赎回（含收益 ¥{profit_share:,.2f}）", channel="agent", status="success",
                      idempotency_key=idempotency_key)
    db.add(txn)
    db.commit()
    return dict(code="OK", holding_id=holding.id, redeemed=req.amount, profit_settled=profit_share,
                payout=payout, holding_status=holding.status,
                balance_after=round(account.balance, 2), transaction_id=txn.id)