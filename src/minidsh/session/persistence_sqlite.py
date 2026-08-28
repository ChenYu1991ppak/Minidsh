"""SQLite 持久化后端。

源码对应：session-persistence-sqlite/src/index.ts:99（appendBatch :284、loadStored :207）。

物理形态：单个 ``{root}/sessions.db``；两表：
- ``sessions(session_id TEXT PRIMARY KEY)`` —— 会话索引（list 用）
- ``events(session_id TEXT, seq INTEGER, type TEXT, payload TEXT)`` —— 事件行，payload 存 JSON 串；
  以 (session_id, seq) 为主键保证 seq 天然无重复。

与 jsonl 后端保证同一 ``PersistenceBackend`` 契约下的**回放等价**：同一会话写入两后端，
load_stored 得到的 ``SessionEvent`` 序列必须逐条相等。这是 T5 的强制验收。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .event import SessionEvent
from .persistence import PersistenceBackend

__all__ = ["SqliteSessionPersistence"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS events (
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    type       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);
"""


class SqliteSessionPersistence(PersistenceBackend):
    """SQLite 存储适配器：{root}/sessions.db。"""

    def __init__(self, root: str | Path, db_name: str = "sessions.db"):
        self.db_path = Path(root) / db_name
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __del__(self):
        # GC 兜底：忘显式 close 时清理连接，避免 ResourceWarning / 泄漏。
        # 捕获一切异常——解释器关闭期全局可能已拆除，此时关闭连接会失败，忽略即可。
        try:
            self._conn.close()
        except Exception:
            pass

    def append_batch(self, session_id: str, events: list[SessionEvent]) -> None:
        if not events:
            return
        with self._conn:  # 事务：整批要么全进要么全不进
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,)
            )
            self._conn.executemany(
                "INSERT OR REPLACE INTO events (session_id, seq, type, payload) "
                "VALUES (?, ?, ?, ?)",
                [
                    (session_id, e.seq, e.type, json.dumps(e.payload, ensure_ascii=False))
                    for e in events
                ],
            )

    def load_stored(self, session_id: str) -> list[SessionEvent] | None:
        rows = self._conn.execute(
            "SELECT seq, type, payload FROM events WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        # 既有会话但无事件 → 空 list（区别于「不存在的会话」返回 None）
        exists = self._conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if exists is None:
            return None
        return [
            SessionEvent(session_id, seq, type, json.loads(payload))
            for seq, type, payload in rows
        ]

    def list(self) -> list[str]:
        rows = self._conn.execute("SELECT session_id FROM sessions ORDER BY session_id").fetchall()
        return [r[0] for r in rows]