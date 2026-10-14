"""账户安全 API（doc 02 §4.6）：修改登录密码（🔴 工具 change_password 的 API 落点）。

服务端强校验：旧密码匹配；新密码 ≥8 位且同时含字母与数字；不得与旧密码相同。
"""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from .accounts import current_user
from .transfers import _err

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=60)
    new_password: str = Field(min_length=1, max_length=60)


def _complexity_ok(pw: str) -> bool:
    return len(pw) >= 8 and bool(re.search(r"[A-Za-z]", pw)) and bool(re.search(r"\d", pw))


@router.post("/change-password")
def change_password(req: ChangePasswordRequest, user_id: str = Depends(current_user),
                    db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise _err(404, "USER_NOT_FOUND", "用户不存在")
    if req.old_password != user.login_password:
        raise _err(400, "OLD_PASSWORD_INCORRECT", "原密码不正确")
    if not _complexity_ok(req.new_password):
        raise _err(400, "WEAK_NEW_PASSWORD", "新密码需至少 8 位，且同时包含字母和数字")
    if req.new_password == req.old_password:
        raise _err(400, "SAME_AS_OLD", "新密码不能与原密码相同")
    user.login_password = req.new_password
    db.commit()
    return dict(code="OK", message="密码已更新")
