"""卡片 API（doc 02 §4.4）：列表 / 虚拟卡申请 / 额度调整 / 冻结解冻 / 挂失解挂。

状态机：正常 ⇄ 冻结；正常/冻结 → 挂失 →（解挂）正常。挂失卡禁止冻结/解冻/调额。
状态转换幂等：重复 freeze 返回当前状态（changed=false），不产生副作用。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Card
from .accounts import current_user
from .transfers import _err, _next_id

router = APIRouter(prefix="/api/cards", tags=["cards"])

VIRTUAL_DAILY_LIMIT = 5000.0
MAX_DAILY_LIMIT = 200000.0


def _card_dict(c: Card) -> dict:
    return dict(id=c.id, card_no_masked=c.card_no_masked, type=c.type,
                credit_limit=c.credit_limit, daily_limit=c.daily_limit, status=c.status)


def _own_card(db: Session, card_id: str, user_id: str) -> Card:
    card = db.get(Card, card_id)
    if card is None or card.user_id != user_id:
        raise _err(404, "CARD_NOT_FOUND", "卡片不存在")
    return card


@router.get("")
def list_cards(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.query(Card).filter(Card.user_id == user_id).order_by(Card.id).all()
    return {"items": [_card_dict(c) for c in rows], "total": len(rows)}


@router.post("/apply-virtual")
def apply_virtual(user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """虚拟卡申请：即申即得，默认单日限额 ¥5,000（卡bin 6228）。"""
    n = db.query(Card).count() + 1
    card = Card(id=_next_id(db, Card, "cd", 3), user_id=user_id,
                card_no_masked=f"6228 **** **** {8800 + n:04d}", type="虚拟",
                credit_limit=0.0, daily_limit=VIRTUAL_DAILY_LIMIT, status="正常")
    db.add(card)
    db.commit()
    return dict(code="OK", **_card_dict(card))


class LimitRequest(BaseModel):
    daily_limit: float = Field(gt=0)


@router.post("/{card_id}/limit")
def adjust_limit(card_id: str, req: LimitRequest, user_id: str = Depends(current_user),
                 db: Session = Depends(get_db)) -> dict:
    card = _own_card(db, card_id, user_id)
    if card.status == "挂失":
        raise _err(409, "CARD_LOST", "卡片已挂失，请先解挂")
    if req.daily_limit > MAX_DAILY_LIMIT:
        raise _err(400, "INVALID_LIMIT", f"单日限额上限 ¥{MAX_DAILY_LIMIT:,.0f}")
    card.daily_limit = round(req.daily_limit, 2)
    db.commit()
    return dict(code="OK", **_card_dict(card))


@router.post("/{card_id}/freeze")
def freeze(card_id: str, user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    card = _own_card(db, card_id, user_id)
    if card.status == "挂失":
        raise _err(409, "CARD_LOST", "卡片已挂失")
    changed = card.status != "冻结"
    card.status = "冻结"
    db.commit()
    return dict(code="OK", changed=changed, **_card_dict(card))


@router.post("/{card_id}/unfreeze")
def unfreeze(card_id: str, user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    card = _own_card(db, card_id, user_id)
    if card.status == "挂失":
        raise _err(409, "CARD_LOST", "卡片已挂失，请先解挂")
    changed = card.status != "正常"
    card.status = "正常"
    db.commit()
    return dict(code="OK", changed=changed, **_card_dict(card))


@router.post("/{card_id}/report-loss")
def report_loss(card_id: str, user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    card = _own_card(db, card_id, user_id)
    changed = card.status != "挂失"
    card.status = "挂失"
    db.commit()
    return dict(code="OK", changed=changed, **_card_dict(card))


@router.post("/{card_id}/cancel-loss")
def cancel_loss(card_id: str, user_id: str = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    card = _own_card(db, card_id, user_id)
    if card.status != "挂失":
        raise _err(409, "INVALID_STATE", "仅挂失状态的卡片可解挂")
    card.status = "正常"
    db.commit()
    return dict(code="OK", changed=True, **_card_dict(card))
