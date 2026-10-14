"""轻量轮询调度器（doc 03 §6.2，跨场景联动发动机）。

- 任务执行权在 bank-core（钱和事都在银行侧）；agent-service 仅创建任务 + 接收 /api/internal/notify 回调；
- 触发方式：① 后台协程轮询（SCHEDULER_POLL_SEC，默认 30s）② POST /api/admin/scheduler/run-now（演示加速）；
- 幂等：资金类流水幂等键 = f"{task.id}:{next_run_at[:10]}"，重复触发不双扣；失败 retry_count+1，≥3 置 failed。
"""
import json
import os
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from .models import Account, Contact, ScheduledTask, Transaction
from .routers.transfers import _next_id

AGENT_NOTIFY_URL = os.environ.get("AGENT_NOTIFY_URL", "http://127.0.0.1:8000/api/internal/notify")
MAX_RETRY = 3

TASK_TYPES = ("transfer", "gift_order", "reminder", "fund_unlock")


class TaskExecError(Exception):
    """任务执行失败（余额不足等），进入 retry/failed 路径。"""


def _notify(user_id: str, event_type: str, title: str, content: str, trace_id: str) -> bool:
    """通知契约（doc 03 §6.2）：POST agent /api/internal/notify；agent 不在线不阻断任务。"""
    try:
        with httpx.Client(timeout=1.5, trust_env=False) as c:
            r = c.post(AGENT_NOTIFY_URL, json={"user_id": user_id, "event_type": event_type,
                                               "title": title, "content": content,
                                               "trace_id": trace_id})
        return r.status_code == 200
    except Exception:  # noqa: BLE001  通知失败不影响资金结果
        return False


def _checking(db: Session, user_id: str) -> Account:
    account = db.query(Account).filter(Account.user_id == user_id, Account.type == "checking").first()
    if account is None:
        raise TaskExecError("未找到活期账户")
    return account


def _post_txn(db: Session, account: Account, amount: float, category: str,
              counterparty: str, remark: str, idem_key: str) -> Transaction:
    txn = Transaction(id=_next_id(db, Transaction, "t"), account_id=account.id,
                      amount=round(amount, 2), category=category, counterparty=counterparty,
                      remark=remark, channel="scheduler", status="success",
                      idempotency_key=idem_key)
    db.add(txn)
    return txn


def _exec_transfer(db: Session, task: ScheduledTask, payload: dict, idem: str) -> str:
    contact = db.get(Contact, payload.get("to_contact_id", ""))
    if contact is None or contact.user_id != task.user_id:
        raise TaskExecError("收款人不存在")
    amount = float(payload.get("amount") or 0)
    account = _checking(db, task.user_id)
    if db.query(Transaction).filter(Transaction.idempotency_key == idem).first():
        return f"已执行过（幂等跳过），收款人 {contact.name} ¥{amount:,.2f}"
    if account.balance - account.frozen_amount < amount:
        raise TaskExecError("余额不足，定时转账失败")
    account.balance = round(account.balance - amount, 2)
    _post_txn(db, account, -amount, "转账", contact.name, payload.get("remark", "定时转账"), idem)
    return f"已向 {contact.name} 转账 ¥{amount:,.2f}（定时任务）"


def _exec_gift_order(db: Session, task: ScheduledTask, payload: dict, idem: str) -> str:
    items = payload.get("items") or []
    if isinstance(items, str):
        items = [items]
    amount = float(payload.get("amount") or payload.get("budget") or 0)
    merchant = payload.get("merchant") or "礼品商城"
    recipient = payload.get("recipient") or "家人"
    if amount <= 0:
        raise TaskExecError("礼品订单缺少金额")
    account = _checking(db, task.user_id)
    if db.query(Transaction).filter(Transaction.idempotency_key == idem).first():
        return f"礼品订单已下过（幂等跳过）：{'、'.join(items)}"
    if account.balance - account.frozen_amount < amount:
        raise TaskExecError("可用余额不足，礼品下单失败")
    account.balance = round(account.balance - amount, 2)
    _post_txn(db, account, -amount, "购物", merchant,
              f"礼品订购：{'、'.join(items)}（送{recipient}）", idem)
    return f"已为{recipient}订购 {'、'.join(items)}，¥{amount:,.2f}（商户：{merchant}）"


def _exec_fund_unlock(db: Session, task: ScheduledTask, payload: dict, idem: str) -> str:
    amount = float(payload.get("amount") or 0)
    account = _checking(db, task.user_id)
    if db.query(Transaction).filter(Transaction.idempotency_key == idem).first():
        return f"资金已解冻过（幂等跳过）¥{amount:,.2f}"
    account.frozen_amount = round(max(0.0, account.frozen_amount - amount), 2)
    # 解冻不产生资金流水（只是可用性变化），写一条 0 元流水留痕以承载幂等键
    _post_txn(db, account, 0.0, "其他", "资金解锁", payload.get("reason", "定时解锁"), idem)
    return f"已解冻资金 ¥{amount:,.2f}，当前冻结 ¥{account.frozen_amount:,.2f}"


def execute_task(db: Session, task: ScheduledTask) -> dict:
    """执行单条任务：按类型分发 → 状态流转 → 通知。返回 {ok, detail|error, notified}。"""
    payload = json.loads(task.payload_json or "{}")
    run_date = (task.next_run_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))[:10]
    idem = f"{task.id}:{run_date}"
    title_map = {"transfer": "定时转账", "gift_order": "礼品订单",
                 "reminder": payload.get("title") or "提醒", "fund_unlock": "资金解锁"}
    try:
        if task.task_type == "transfer":
            detail = _exec_transfer(db, task, payload, idem)
        elif task.task_type == "gift_order":
            detail = _exec_gift_order(db, task, payload, idem)
        elif task.task_type == "fund_unlock":
            detail = _exec_fund_unlock(db, task, payload, idem)
        elif task.task_type == "reminder":
            detail = payload.get("text") or "您有一条提醒"
        else:
            raise TaskExecError(f"未知任务类型 {task.task_type}")
        ok, error = True, ""
    except TaskExecError as e:
        ok, detail, error = False, "", str(e)

    if ok:
        if task.recurrence == "monthly":
            y, m = int(task.next_run_at[:4]), int(task.next_run_at[5:7])
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
            task.next_run_at = f"{y}-{m:02d}" + task.next_run_at[7:]
        else:
            task.status = "done"
    else:
        task.retry_count += 1
        if task.retry_count >= MAX_RETRY:
            task.status = "failed"
    db.commit()

    notified = _notify(task.user_id,
                       "task_executed" if ok else "task_failed",
                       f"【智银】{title_map.get(task.task_type, '任务')}{'已完成' if ok else '失败'}",
                       detail if ok else f"{title_map.get(task.task_type, '任务')}执行失败：{error}",
                       trace_id=f"task_{task.id}")
    return dict(task_id=task.id, task_type=task.task_type, ok=ok,
                detail=detail, error=error, status=task.status, notified=notified)


def run_due(db: Session, now: str | None = None) -> list[dict]:
    """扫描并执行全部到期任务（status=active 且 next_run_at <= now）。"""
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    due = db.query(ScheduledTask).filter(ScheduledTask.status == "active",
                                         ScheduledTask.next_run_at <= now).order_by(ScheduledTask.id).all()
    return [execute_task(db, t) for t in due]