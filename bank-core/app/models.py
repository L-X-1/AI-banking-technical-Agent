"""bank-core ORM 模型（对齐 doc 03 §8.1 DDL 与 doc 02 §3.1 数据字典）。

约定：
- 主键/created_at 采用 TEXT（与 DDL 一致，SQLite datetime(now) 风格字符串）；
- 枚举值：核心 5 表用英文码（DDL CHECK 约束）；其余 4 表按 doc 02 §3.1 中文值；
- 金额单位：元（float，两位小数）。
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("risk_level BETWEEN 1 AND 5", name="ck_users_risk"),)
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    id_card_masked: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    login_password: Mapped[str] = mapped_column(String(60), nullable=False, default="123456")  # M3：change_password 落点
    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_str)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("type IN ('checking','deposit')", name="ck_accounts_type"),
        CheckConstraint("balance >= 0", name="ck_accounts_balance"),
        CheckConstraint("frozen_amount >= 0", name="ck_accounts_frozen"),
    )
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    account_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False, default="checking")
    balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frozen_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    account_no: Mapped[str] = mapped_column(String(30), nullable=False)
    remark: Mapped[str] = mapped_column(String(100), default="")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("status IN ('success','pending','failed','reversed')", name="ck_txn_status"),
    )
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # 正=收入 负=支出
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="其他")
    counterparty: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    remark: Mapped[str] = mapped_column(String(200), default="")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="agent")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_str)


class WealthProduct(Base):
    __tablename__ = "wealth_products"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    annual_yield: Mapped[float] = mapped_column(Float, nullable=False)
    min_amount: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    lock_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WealthHolding(Base):
    __tablename__ = "wealth_holdings"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("wealth_products.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="持有")


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    card_no_masked: Mapped[str] = mapped_column(String(30), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    credit_limit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_limit: Mapped[float] = mapped_column(Float, nullable=False, default=50000.0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="正常")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[str] = mapped_column(String(10), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    merchant: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    cycle: Mapped[str] = mapped_column(String(10), nullable=False, default="月")
    next_billing_date: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="生效")


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        CheckConstraint("task_type IN ('transfer','gift_order','reminder','fund_unlock')", name="ck_task_type"),
        CheckConstraint("status IN ('active','done','failed','cancelled')", name="ck_task_status"),
    )
    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    next_run_at: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    recurrence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_str)