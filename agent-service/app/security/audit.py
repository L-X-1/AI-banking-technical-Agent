"""操作审计（doc 02 §9.3 / doc 03 §2）：trace_id 六类事件全链路，SQLite 落盘，
供 `GET /api/audit/{trace_id}` 回放（答辩杀手锏）与安全自评报告取材。
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any

SIX_EVENTS = ("intent", "plan", "decision", "tool_call", "confirm", "reply")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AuditLog:
    """六类事件：intent / plan / decision / tool_call / confirm / reply。"""

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")     # 多连接并发（与 checkpoint 共库）
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS audit_logs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " trace_id TEXT NOT NULL, session_id TEXT, node TEXT NOT NULL,"
            " payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_logs(trace_id)")
        self._conn.commit()

    def record(self, trace_id: str, session_id: str, node: str, payload: dict[str, Any]) -> None:
        if node not in SIX_EVENTS:
            raise ValueError(f"审计事件必须是六类之一：{SIX_EVENTS}，收到 {node}")
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_logs (trace_id, session_id, node, payload_json, created_at) VALUES (?,?,?,?,?)",
                (trace_id, session_id, node, json.dumps(payload, ensure_ascii=False), _now()),
            )
            self._conn.commit()

    def fetch(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, trace_id, session_id, node, payload_json, created_at FROM audit_logs"
                " WHERE trace_id=? ORDER BY id", (trace_id,)
            ).fetchall()
        return [dict(id=r[0], trace_id=r[1], session_id=r[2], node=r[3],
                     payload=json.loads(r[4]), created_at=r[5]) for r in rows]

    def kinds(self, trace_id: str) -> list[str]:
        return [e["node"] for e in self.fetch(trace_id)]


from ..config import AGENT_DB_PATH  # noqa: E402

audit = AuditLog(AGENT_DB_PATH)
