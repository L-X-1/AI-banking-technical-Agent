"""异常熔断状态机（doc 02 §9.4 / doc 06 §5.2 breaker.py）。

四类触发（doc 02 §9.4 表）：
  T1 单会话连续 3 次工具失败   → open(scope=write)：暂停写操作、仅允许查询、提示人工接管
  T2 MFA 连续 3 次验证失败      → open(scope=session)：锁定会话 15 分钟（倒计时）
  T3 注入检测累计 2 次命中      → open(scope=session)：锁定会话（需重新登录；演示以 15 分钟倒计时代替）
  T4 凌晨 1-5 点大额操作       → 自动升红 + 二次确认（定级由 permission 规则 5 执行，本模块提供判定）

状态机：closed → open →（到期）half_open →（成功）closed /（再失败）open。
状态行持久化于 agent.db `breaker_states` 表，进程重启不丢锁定（doc 05 §3.3 重置脚本口径）。
"""
import os
import sqlite3
import threading
import time
from typing import Any

from ..config import AGENT_DB_PATH

LOCK_TTL_SEC = 15 * 60     # 15 分钟锁定（doc 05 M2#3）
FAIL_STREAK_LIMIT = 3      # T1/T2 连败阈值
INJECTION_LIMIT = 2        # T3 注入累计阈值
NIGHT_WINDOW = (1, 5)      # T4 非活跃时段：凌晨 1-5 点（含，doc 02 §9.4）
NIGHT_LARGE_LIMIT = 2000.0  # T4 "大额" 阈值（单笔 ≥ ¥2000 升红）

_DEFAULT = dict(state="closed", scope="none", trigger="", reason="",
                tool_fail_streak=0, mfa_fail_streak=0, injection_hits=0,
                opened_at=0.0, expires_at=0.0)


def night_risk(hour: int, amount: float, is_write: bool) -> bool:
    """T4 判定：凌晨 1-5 点的 ≥¥2000 写操作 → 升红（permission 规则 5 调用）。"""
    return bool(is_write and NIGHT_WINDOW[0] <= hour <= NIGHT_WINDOW[1]
                and float(amount or 0.0) >= NIGHT_LARGE_LIMIT)


class CircuitBreaker:
    """closed/open/half-open 状态机（doc 05 §2 安全自评模板 §5）。"""

    def __init__(self, path: str = AGENT_DB_PATH) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")     # 与 audit/store/checkpoint 共库并发
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS breaker_states ("
            " session_id TEXT PRIMARY KEY, state TEXT NOT NULL, scope TEXT NOT NULL,"
            " trigger TEXT, reason TEXT, tool_fail_streak INTEGER NOT NULL,"
            " mfa_fail_streak INTEGER NOT NULL, injection_hits INTEGER NOT NULL,"
            " opened_at REAL NOT NULL, expires_at REAL NOT NULL)")
        self._conn.commit()
        self._now = time.time      # 测试注入点：可替换时钟（验证 half_open 到期迁移）

    # ── 持久化行 ─────────────────────────────────────────────
    def _load(self, session_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT state, scope, trigger, reason, tool_fail_streak, mfa_fail_streak,"
            " injection_hits, opened_at, expires_at FROM breaker_states WHERE session_id=?",
            (session_id,)).fetchone()
        if row is None:
            return dict(_DEFAULT)
        keys = ["state", "scope", "trigger", "reason", "tool_fail_streak",
                "mfa_fail_streak", "injection_hits", "opened_at", "expires_at"]
        return dict(zip(keys, row))

    def _save(self, session_id: str, row: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO breaker_states (session_id, state, scope, trigger, reason,"
            " tool_fail_streak, mfa_fail_streak, injection_hits, opened_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(session_id) DO UPDATE SET state=excluded.state, scope=excluded.scope,"
            " trigger=excluded.trigger, reason=excluded.reason,"
            " tool_fail_streak=excluded.tool_fail_streak, mfa_fail_streak=excluded.mfa_fail_streak,"
            " injection_hits=excluded.injection_hits, opened_at=excluded.opened_at,"
            " expires_at=excluded.expires_at",
            (session_id, row["state"], row["scope"], row["trigger"], row["reason"],
             row["tool_fail_streak"], row["mfa_fail_streak"], row["injection_hits"],
             row["opened_at"], row["expires_at"]))
        self._conn.commit()

    # ── 事件记录（doc 03 §1.3 CircuitBreaker.record）──────────
    def record(self, session_id: str, event: str, reason: str = "") -> dict[str, Any]:
        """记录熔断事件：tool_fail / tool_ok / mfa_fail / mfa_ok / injection / reset。"""
        with self._lock:
            row = self._load(session_id)
            now = self._now()
            if event == "tool_fail":
                row["tool_fail_streak"] += 1
                if row["tool_fail_streak"] >= FAIL_STREAK_LIMIT:
                    row.update(state="open", scope="write", trigger="tool_fail",
                               reason=reason or (
                                   f"连续 {FAIL_STREAK_LIMIT} 次工具失败 → 暂停写操作，"
                                   f"仅允许查询，提示人工接管"),
                               opened_at=now, expires_at=now + LOCK_TTL_SEC)
            elif event == "tool_ok":
                row["tool_fail_streak"] = 0
                if row["state"] == "half_open":     # 半开探测成功 → 恢复 closed
                    row.update(state="closed", scope="none", trigger="", reason="",
                               opened_at=0.0, expires_at=0.0)
            elif event == "mfa_fail":
                row["mfa_fail_streak"] += 1
                if row["mfa_fail_streak"] >= FAIL_STREAK_LIMIT:
                    row.update(state="open", scope="session", trigger="mfa_fail",
                               reason=reason or (
                                   f"MFA 连续 {FAIL_STREAK_LIMIT} 次失败 → 锁定会话 "
                                   f"{LOCK_TTL_SEC // 60} 分钟"),
                               opened_at=now, expires_at=now + LOCK_TTL_SEC)
            elif event == "mfa_ok":
                row["mfa_fail_streak"] = 0
                if row["state"] == "half_open":
                    row.update(state="closed", scope="none", trigger="", reason="",
                               opened_at=0.0, expires_at=0.0)
            elif event == "injection":
                row["injection_hits"] += 1
                if row["injection_hits"] >= INJECTION_LIMIT:
                    row.update(state="open", scope="session", trigger="injection",
                               reason=reason or (
                                   f"注入检测累计 {INJECTION_LIMIT} 次命中 → 锁定会话"
                                   f"（需重新登录解锁；演示 {LOCK_TTL_SEC // 60} 分钟倒计时）"),
                               opened_at=now, expires_at=now + LOCK_TTL_SEC)
            elif event == "night_large":   # T4 仅留痕；升红由 permission 规则 5 执行
                pass
            elif event == "reset":
                row = dict(_DEFAULT)
            self._save(session_id, row)
            return dict(row)

    # ── 状态查询（open 且到期 → half_open；session 锁定优先）────
    def status(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._load(session_id)
            if row["state"] == "open" and self._now() >= row["expires_at"]:
                row.update(state="half_open", opened_at=self._now())
                self._save(session_id, row)
            out = dict(row)
            out["locked"] = out["state"] == "open" and out["scope"] == "session"
            out["write_disabled"] = (out["state"] in ("open", "half_open")
                                     and out["scope"] == "write")
            out["seconds_left"] = (max(0, int(row["expires_at"] - self._now()))
                                   if row["state"] == "open" else 0)
            return out

    # ── doc 03 §1.3 接口 ─────────────────────────────────────
    def is_locked(self, session_id: str) -> bool:
        return bool(self.status(session_id)["locked"])

    def locked_reason(self, session_id: str) -> str | None:
        st = self.status(session_id)
        return st["reason"] if st["locked"] else None

    def reset(self, session_id: str) -> None:
        """人工解锁/重新登录（doc 02 §9.4 注入锁定的正规出口）。"""
        self.record(session_id, "reset")


breaker = CircuitBreaker()
