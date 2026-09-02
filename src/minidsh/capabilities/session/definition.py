"""session 能力定义（三角色的「定义」）。

声明 session 能力的核心契约类型：会话事件、追加日志、会话注册表、持久化 seam。
具体实现（jsonl/sqlite）在 ``providers/``；事件流是可观测性的唯一真源。
"""
from __future__ import annotations

from .event import SessionEvent, SessionEventType
from .store import Session, SessionStore
from .persistence import (
    SessionPersistence,
    PersistenceBackend,
    PersistenceCoordinator,
    WriteBehind,
)

__all__ = [
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionStore",
    "SessionPersistence",
    "PersistenceBackend",
    "PersistenceCoordinator",
    "WriteBehind",
]