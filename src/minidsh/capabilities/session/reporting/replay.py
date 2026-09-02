"""重放：从持久化 store 读回会话事件，按时间线重放为可读格式。

``minidsh replay <path>`` 子命令入口（CLI 在 T18 装配）。
支持 jsonl（``sessions/<id>.jsonl``）与 sqlite（``sessions.db``）两类来源，
由 ``load_session_events`` 自动探测。
"""
from __future__ import annotations

from pathlib import Path

from ..event import SessionEvent
from ...persistence.providers.jsonl import JsonlSessionPersistence
from ...persistence.providers.sqlite import SqliteSessionPersistence
from .renderer import render_event

__all__ = ["load_session_events", "replay_session"]


def load_session_events(path: str | Path, session_id: str | None = None) -> list[SessionEvent]:
    """从磁盘读回事件流。自动探测 jsonl 单文件 vs sqlite 库。

    - ``path`` 指向 jsonl 文件：读该文件。
    - ``path`` 指向目录（含 sessions.db）：用 sqlite 后端；``session_id`` 必填。
    - ``path`` 指向目录（含 sessions/）：用 jsonl 后端；``session_id`` 必填。
    """
    p = Path(path)
    if p.is_file():  # 直接给 jsonl 文件
        backend = JsonlSessionPersistence(p.parent.parent)
        events = backend.load_stored(p.stem)
        return events or []
    if p.is_dir():
        if (p / "sessions.db").exists():
            backend = SqliteSessionPersistence(p)
            if session_id is None:
                raise ValueError("sqlite 来源需要指定 session_id")
            events = backend.load_stored(session_id)
            backend.close()
            return events or []
        if (p / "sessions").is_dir():
            backend = JsonlSessionPersistence(p)
            if session_id is None:
                raise ValueError("jsonl 目录来源需要指定 session_id")
            events = backend.load_stored(session_id)
            return events or []
    raise FileNotFoundError(f"找不到可重放的存储：{path}")


def replay_session(events: list[SessionEvent]) -> str:
    """把事件列表渲染成按 seq 排序的多行文本（重放主载体）。"""
    ordered = sorted(events, key=lambda e: e.seq)
    return "\n".join(render_event(e) for e in ordered)