"""bank-core FastAPI 入口：建表 + 幂等种子 + 路由挂载（doc 02 §4）+ 调度器轮询（doc 03 §6.2）。"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  确保 ORM 模型注册到 Base.metadata
from .database import Base, SessionLocal, engine
from .routers import accounts, auth, billing, cards, contacts, subscriptions, tasks, transfers, wealth
from .scheduler import run_due
from .seed import seed_if_empty

SCHEDULER_POLL_SEC = float(os.environ.get("SCHEDULER_POLL_SEC", "30"))  # 0 = 关闭后台轮询


def _run_due_once() -> int:
    with SessionLocal() as db:
        return len(run_due(db))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seeded = seed_if_empty(db)
    if seeded:
        print("[bank-core] 种子数据写入完成（doc 03 §9）")
    stop = asyncio.Event()
    bg: asyncio.Task | None = None
    if SCHEDULER_POLL_SEC > 0:
        async def _loop() -> None:
            while not stop.is_set():
                try:
                    n = await asyncio.to_thread(_run_due_once)
                    if n:
                        print(f"[bank-core] 调度器执行到期任务 {n} 条")
                except Exception as e:  # noqa: BLE001  轮询失败不致命，下周期重试
                    print(f"[bank-core] 调度器轮询异常：{e}")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=SCHEDULER_POLL_SEC)
                except asyncio.TimeoutError:
                    pass
        bg = asyncio.create_task(_loop())
    yield
    stop.set()
    if bg is not None:
        await asyncio.gather(bg, return_exceptions=True)


app = FastAPI(title="bank-core", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (accounts, contacts, transfers, billing, wealth, cards, subscriptions, tasks, auth):
    app.include_router(r.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "bank-core"}
