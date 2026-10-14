"""转账 API（doc 02 §4.1 / doc 03 §8.2）：写操作强制 Idempotency-Key；支持定时转账转 scheduled_tasks。"""
import json

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Contact, ScheduledTask, Transaction
from .accounts import current_user

router = APIRouter(prefix="/api", tags=["transfers"])

SINGLE_LIMIT = 50000.0  # doc 02 §8.2：单笔 > 5 万拒绝


class TransferRequest(BaseModel):
    to_contact_id: str
    amount: float = Field(gt=0, le=SINGLE_LIMIT)
    remark: str = Field(default="", max_length=50)
    schedule_time: str | None = None  # 有值 = 定时转账 → scheduled_tasks


class AaSplitRequest(BaseModel):
    total_amount: float = Field(gt=0, le=SINGLE_LIMIT)
    contact_ids: list[str] = Field(min_length=1)
    remark: str = Field(default="", max_length=50)


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _next_id(db: Session, model, prefix: str, width: int = 5) -> str:
    last = db.query(model).order_by(model.id.desc()).first()
    n = int(last.id[len(prefix):]) + 1 if last else 1
    return f"{prefix}{n:0{width}d}"


def _checking_account(db: Session, user_id: str) -> Account:
    account = db.query(Account).filter(Account.user_id == user_id, Account.type == "checking").first()
    if account is None:
        raise _err(404, "ACCOUNT_NOT_FOUND", "未找到活期账户")
    return account


@router.post("/transfers")
def create_transfer(req: TransferRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if not idempotency_key:
        raise _err(400, "MISSING_IDEMPOTENCY_KEY", "写操作必须携带 Idempotency-Key 头")

    # 幂等重放：同一 key 直接返回首次结果（doc 02 §3.1 幂等设计）
    replay = db.query(Transaction).filter(Transaction.idempotency_key == idempotency_key).first()
    if replay is not None:
        account = _checking_account(db, user_id)
        return dict(code="IDEMPOTENT_REPLAY", transaction_id=replay.id, amount=abs(replay.amount),
                    counterparty=replay.counterparty, balance_after=round(account.balance, 2),
                    executed_at=replay.created_at)

    contact = db.get(Contact, req.to_contact_id)
    if contact is None or contact.user_id != user_id:
        raise _err(404, "CONTACT_NOT_FOUND", "收款人不存在")
    account = _checking_account(db, user_id)

    if req.schedule_time:  # 定时转账：不立即扣款，落 scheduled_tasks（doc 02 §4.1）
        task = ScheduledTask(id=_next_id(db, ScheduledTask, "st", 6), user_id=user_id, task_type="transfer",
                             payload_json=json.dumps({"to_contact_id": contact.id, "amount": req.amount,
                                                      "remark": req.remark, "idempotency_key": idempotency_key},
                                                     ensure_ascii=False),
                             next_run_at=req.schedule_time, recurrence=None, status="active")
        db.add(task)
        db.commit()
        return dict(code="SCHEDULED", task_id=task.id, amount=req.amount, counterparty=contact.name,
                    next_run_at=task.next_run_at)

    if account.balance - account.frozen_amount < req.amount:
        raise _err(400, "INSUFFICIENT_BALANCE", "余额不足")

    account.balance = round(account.balance - req.amount, 2)
    txn = Transaction(id=_next_id(db, Transaction, "t"), account_id=account.id, amount=-round(req.amount, 2),
                      category="转账", counterparty=contact.name, remark=req.remark, channel="agent",
                      status="success", idempotency_key=idempotency_key)
    db.add(txn)
    db.commit()
    return dict(code="OK", transaction_id=txn.id, amount=req.amount, counterparty=contact.name,
                balance_after=round(account.balance, 2), executed_at=txn.created_at)


@router.post("/transfers/aa-split")
def create_aa_split(req: AaSplitRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """AA 拆分收款：发起人已垫付 total_amount，向 N 位成员各生成 share 收款单（pending 收入）。"""
    if not idempotency_key:
        raise _err(400, "MISSING_IDEMPOTENCY_KEY", "写操作必须携带 Idempotency-Key 头")
    replay = db.query(Transaction).filter(Transaction.idempotency_key == f"{idempotency_key}:aa").first()
    if replay is not None:
        return dict(code="IDEMPOTENT_REPLAY", requests=[])

    share = round(req.total_amount / (len(req.contact_ids) + 1), 2)
    account = _checking_account(db, user_id)
    requests = []
    for idx, contact_id in enumerate(req.contact_ids):
        contact = db.get(Contact, contact_id)
        if contact is None or contact.user_id != user_id:
            raise _err(404, "CONTACT_NOT_FOUND", f"成员 {contact_id} 不存在")
        txn = Transaction(id=_next_id(db, Transaction, "t"), account_id=account.id, amount=share,
                          category="转账", counterparty=f"{contact.name}（AA 收款）", remark=req.remark,
                          channel="agent", status="pending",
                          idempotency_key=f"{idempotency_key}:aa" if idx == 0 else None)
        db.add(txn)
        db.flush()
        requests.append(dict(contact_id=contact.id, name=contact.name, amount=share, transaction_id=txn.id))
    db.commit()
    return dict(code="OK", total_amount=req.total_amount, share=share, requests=requests)
