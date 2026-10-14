"""待确认动作 / MFA 挑战的 SQLite 持久化（doc 02 §3.2 pending_actions / mfa_challenges 表）。

M1 为进程内 dict 登记（重启丢状态）；M2 迁移 SQLite。JsonStore = 内存缓存 + 写穿透：
读走缓存（与原 dict API 兼容），写经 `__setitem__` / `patch` 立即落库。
"""
import json
import os
import sqlite3
import threading
import time
from collections.abc import Iterator, MutableMapping
from typing import Any


class JsonStore(MutableMapping):
    """dict 兼容的写穿透 SQLite 存储（值必须可 JSON 序列化）。"""

    def __init__(self, db_path: str, table: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._table = table
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")     # 与 audit/breaker/checkpoint 共库并发
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            " key TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL)")
        self._conn.commit()
        self._cache: dict[str, Any] = {
            k: json.loads(v) for k, v in
            self._conn.execute(f"SELECT key, data_json FROM {table}").fetchall()}

    # ── MutableMapping ──────────────────────────────────────
    def __getitem__(self, key: str) -> Any:
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = value
            self._upsert(key, value)

    def __delitem__(self, key: str) -> None:
        with self._lock:
            del self._cache[key]
            self._conn.execute(f"DELETE FROM {table_or(self._table)} WHERE key=?", (key,))
            self._conn.commit()

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._cache))

    def __len__(self) -> int:
        return len(self._cache)

    # ── 持久化更新（状态迁移的唯一写入口）────────────────────
    def patch(self, key: str, **fields: Any) -> None:
        """就地合并字段并落库（原地改 dict 的调用点统一走这里）。"""
        with self._lock:
            row = self._cache.get(key)
            if row is None:
                raise KeyError(key)
            row.update(fields)
            self._upsert(key, row)

    def _upsert(self, key: str, value: Any) -> None:
        self._conn.execute(
            f"INSERT INTO {self._table} (key, data_json, updated_at) VALUES (?,?,?)"
            f" ON CONFLICT(key) DO UPDATE SET data_json=excluded.data_json,"
            f" updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False),
             time.strftime("%Y-%m-%d %H:%M:%S")))
        self._conn.commit()


def table_or(name: str) -> str:
    """表名来源仅限白名单（防 f-string 注入）；调用方恒为模块内字段。"""
    if not name.isidentifier():
        raise ValueError(f"非法表名：{name}")
    return name


from ..config import AGENT_DB_PATH  # noqa: E402

PENDING_ACTIONS = JsonStore(AGENT_DB_PATH, "pending_actions")   # doc 02 §3.2
MFA_CHALLENGES = JsonStore(AGENT_DB_PATH, "mfa_challenges")      # doc 02 §3.2
