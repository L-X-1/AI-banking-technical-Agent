"""收款人检索 API（doc 02 §4.1；同名消歧数据源，支撑 resolve_contact 工具）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Contact
from .accounts import current_user

router = APIRouter(prefix="/api", tags=["contacts"])


@router.get("/contacts")
def search_contacts(keyword: str = "", user_id: str = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    """按姓名/手机号/备注模糊匹配；keyword 为空返回全部通讯录。"""
    q = db.query(Contact).filter(Contact.user_id == user_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Contact.name.like(like) | Contact.phone.like(like) | Contact.remark.like(like))
    rows = q.order_by(Contact.id).all()
    return {"items": [dict(id=c.id, name=c.name, phone=c.phone, remark=c.remark,
                           phone_tail=c.phone[-4:], account_no_tail=c.account_no[-4:]) for c in rows],
            "total": len(rows)}
