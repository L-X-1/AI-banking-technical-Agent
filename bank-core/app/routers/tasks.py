"""定时/联动任务 API（doc 02 §4.5 + doc 03 §6）：创建/查询/取消 + 演示加速 run-now。

任务执行逻辑在 app/scheduler.py（执行权归属 bank-core，doc 03 §6.1）。
"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ScheduledTask
from ..scheduler import TASK_TYPES, run_due
from .accounts import current_user
from .transfers import _err, _next_id

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])


def _task_dict(t: ScheduledTask) -> dict:
    return dict(id=t.id, task_type=t.task_type, payload=json.loads(t.payload_json or "{}"),
                next_run_at=t.next_run_at, recurrence=t.recurrence, status=t.status,
                retry_count=t.retry_count, created_at=t.created_at)


def _normalize_run_at(raw: str) -> str:
    """'YYYY-MM-DD[ HH:MM[:SS]]' → 'YYYY-MM-DD HH:MM:SS'（界面/Planner 常省略时间）。"""
    raw = (raw or "").strip().replace("T", " ")
    date, _, clock = raw.partition(" ")
    try:
        y, m, d = (int(x) for x in date.split("-"))
        parts = [int(x) for x in clock.split(":") if x != ""]
        hh, mm, ss = (parts + [0, 0, 0])[:3]
        return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"
    except (ValueError, IndexError):
        raise _err(400, "BAD_RUN_AT", "next_run_at 需为 YYYY-MM-DD[ HH:MM[:SS]]")


class CreateTaskRequest(BaseModel):
    task_type: str
    payload: dict = Field(default_factory=dict)
    next_run_at: str
    recurrence: str | None = None


@router.post("/scheduled-tasks")
def create_task(req: CreateTaskRequest, user_id: str = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    if req.task_type not in TASK_TYPES:
        raise _err(400, "BAD_TASK_TYPE", f"task_type 仅支持 {'/'.join(TASK_TYPES)}")
    if req.recurrence not in (None, "monthly"):
        raise _err(400, "BAD_RECURRENCE", "recurrence 仅支持 monthly 或空")
    task = ScheduledTask(id=_next_id(db, ScheduledTask, "st", 6), user_id=user_id,
                         task_type=req.task_type, payload_json=json.dumps(req.payload, ensure_ascii=False),
                         next_run_at=_normalize_run_at(req.next_run_at),
                         recurrence=req.recurrence, status="active")
    db.add(task)
    db.commit()
    return dict(code="OK", **_task_dict(task))


@router.get("/scheduled-tasks")
def list_tasks(status: str | None = None, user_id: str = Depends(current_user),
               db: Session = Depends(get_db)) -> dict:
    q = db.query(ScheduledTask).filter(ScheduledTask.user_id == user_id)
    if status:
        q = q.filter(ScheduledTask.status == status)
    rows = q.order_by(ScheduledTask.next_run_at).all()
    return {"items": [_task_dict(t) for t in rows], "total": len(rows)}


@router.delete("/scheduled-tasks/{task_id}")
def cancel_task(task_id: str, user_id: str = Depends(current_user),
                db: Session = Depends(get_db)) -> dict:
    t = db.get(ScheduledTask, task_id)
    if t is None or t.user_id != user_id:
        raise _err(404, "TASK_NOT_FOUND", "任务不存在")
    changed = t.status == "active"
    if changed:
        t.status = "cancelled"
        db.commit()
    return dict(code="OK", changed=changed, **_task_dict(t))


@router.post("/admin/scheduler/run-now")
def run_now(now: str | None = None, db: Session = Depends(get_db)) -> dict:
    """演示加速（doc 03 §6.2）：立即执行全部到期任务；now 可注入用于测试。"""
    executed = run_due(db, now)
    return dict(code="OK", executed=executed, count=len(executed))
