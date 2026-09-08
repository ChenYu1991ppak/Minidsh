"""persistence 能力：会话持久化（ctx.sessionPersistence）。

definition.py 声明 SessionPersistence / PersistenceBackend / PersistenceCoordinator 契约；
providers/jsonl.py 与 providers/sqlite.py 是两平级 provider，各自 provide 同一服务名
``sessionPersistence``，装配期经清单选择——见 SPEC-provider-select「提供方可替换」。
"""
from .definition import (
    SessionPersistence,
    PersistenceBackend,
    PersistenceCoordinator,
    WriteBehind,
)

__all__ = ["SessionPersistence", "PersistenceBackend", "PersistenceCoordinator", "WriteBehind"]
