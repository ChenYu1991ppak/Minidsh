"""session 能力定义（三角色的「定义」）。

声明 session 能力的核心契约类型：会话事件、追加日志、会话注册表。
持久化是独立的 ``capabilities/persistence`` 能力，不再属本包。
"""
from __future__ import annotations

from .event import SessionEvent, SessionEventType
from .store import Session, SessionStore

__all__ = [
    "Session",
    "SessionEvent",
    "SessionEventType",
    "SessionStore",
]