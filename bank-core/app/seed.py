"""种子数据写入（幂等）：表为空时写入 doc 03 §9 全量演示数据。

交易流水配方（doc 03 §9.2）：12 个月 ×（餐饮18/交通12/购物6/居住1/订阅5/转账2/薪资1/理财1）
+ 异常埋点：2026-09-14 03:22 数码商城 -4,999.00（凌晨陌生商户，账单异常识别主角）。
遗忘订阅：云存储 ¥68/月 连续 12 个月扣费（订阅识别主角）。
"""
import calendar
import random
from datetime import datetime

from sqlalchemy.orm import Session

from . import seed_data as S
from .models import (Account, Card, Contact, Subscription, Transaction, User,
                     WealthHolding, WealthProduct)

MEALS = ["肯德基", "瑞幸咖啡", "海底捞", "老乡鸡", "美团外卖", "全家便利店"]
TRIPS = ["地铁出行", "滴滴出行", "共享单车", "高铁 12306"]
SHOPS = ["京东", "淘宝", "优衣库", "小米之家", "山姆超市"]
SUBS = [("云存储", 68.0), ("视频会员", 25.0), ("音乐会员", 15.0), ("新闻订阅", 12.0), ("云盘 Pro", 30.0),
        ("iCloud 扩容", 21.0)]   # 只进流水、不进 subscriptions 表 → detect 的"新识别候选"（M3#3 演示）


def build_transactions(account_id: str = "a001") -> list[dict]:
    rng = random.Random(20260923)
    rows: list[dict] = []
    seq = 0

    def add(created: datetime, amount: float, category: str, counterparty: str, remark: str = "", channel: str = "app", status: str = "success") -> None:
        nonlocal seq
        seq += 1
        rows.append(dict(id=f"t{seq:05d}", account_id=account_id, amount=round(amount, 2), category=category,
                         counterparty=counterparty, remark=remark, channel=channel, status=status,
                         idempotency_key=None, created_at=created.strftime("%Y-%m-%d %H:%M:%S")))

    y, m = 2025, 10
    for _ in range(12):
        last_day = calendar.monthrange(y, m)[1]
        cap = 23 if (y, m) == (2026, 9) else last_day  # 当月演示日至 09-23

        def d(day: int, hh: int = 0, mm: int = 0) -> datetime:
            return datetime(y, m, min(max(1, day), cap), hh, mm)

        for _ in range(5):
            add(d(rng.randint(1, cap), rng.randint(7, 22), rng.randint(0, 59)), -rng.uniform(15, 120), "餐饮", rng.choice(MEALS), channel="pos")
        for _ in range(3):
            add(d(rng.randint(1, cap), rng.randint(7, 22), rng.randint(0, 59)), -rng.uniform(2, 50), "交通", rng.choice(TRIPS))
        for _ in range(2):
            add(d(rng.randint(1, cap), rng.randint(9, 22), rng.randint(0, 59)), -rng.uniform(50, 800), "购物", rng.choice(SHOPS))
        add(d(5, 10, 0), -3500.00, "居住", "房东-陈姐", "每月房租")
        for merchant, amount in SUBS:
            add(d(14 if merchant == "云存储" else rng.randint(1, cap), 8, 30), -amount, "订阅", merchant, "自动扣费")
        if (y * 12 + m) % 3 == 0:
            add(d(1, 9, 0), -198.00, "订阅", "健身 App", "季度自动扣费")
        add(d(2, 20, 5), -rng.uniform(100, 2000), "转账", "王芳", "家用")   # 固定月初，避免干扰"当日累计"演示
        add(d(5, 19, 40), -rng.uniform(100, 2000), "转账", "妈妈", "孝敬")
        add(d(10, 9, 0), 25000.00, "其他", "薪资入账", "月薪", channel="app")
        add(d(12, 11, 0), -1000.00, "理财", "稳健添利 30 天", "月度定投")
        m += 1
        if m == 13:
            m, y = 1, y + 1

    add(datetime(2026, 9, 14, 3, 22), -4999.00, "购物", "数码商城", "陌生商户·凌晨异常交易", channel="pos")
    rows.sort(key=lambda r: r["created_at"])
    return rows


def seed_if_empty(db: Session) -> bool:
    if db.query(User).first() is not None:
        return False
    db.add_all([User(**row) for row in S.USERS])
    db.add_all([Account(**row) for row in S.ACCOUNTS])
    db.add_all([Contact(**row) for row in S.CONTACTS])
    db.add_all([WealthProduct(**row) for row in S.PRODUCTS])
    db.add_all([WealthHolding(**row) for row in S.HOLDINGS])
    db.add_all([Card(**row) for row in S.CARDS])
    db.add_all([Subscription(**row) for row in S.SUBSCRIPTIONS])
    db.add_all([Transaction(**row) for row in build_transactions()])
    db.commit()
    return True