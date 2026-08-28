"""会话追加日志与会话注册表。

源码对应：
- ``Session``  ↔ packages/core/session/src/index.ts:425（append :604-653）
- ``SessionStore`` ↔ packages/core/session/src/index.ts:792（ctx.sessions，即 SessionStore）

``Session`` 是「只追加、不可改」的事件日志；``SessionStore`` 是会话注册表服务，
提供创建/查询/枚举。事件经 ``session/event`` 广播，供持久化/trace/compaction 消费。

[教学简化] 真实 Store 有 prepare/commitPrepared 两段式创建与 enter/announce 登记；
此处直接创建（create 即注册）。id 用自增序号，真实版是 uuid，等价机制。
"""
from __future__ import annotations

from .event import SessionEvent, SessionEventType

__all__ = ["Session", "SessionStore"]


class Session:
    """append-only 事件日志。seq == len(log)，事件创建后不可改。"""

    def __init__(self, ctx, session_id: str):
        self.ctx = ctx
        self.id = session_id
        self.log: list[SessionEvent] = []

    def append(self, type: str, payload: dict | None = None):
        """追加一条事件（index.ts:604-653）：seq == len(log)，广播 ``session/event``。

        传入 payload 若为 None，用空 dict；frozen 事件 + 白名单校验在
        ``SessionEvent.__post_init__`` 完成。广播是同步的（内核同步，spec §11-5）。
        """
        event = SessionEvent(self.id, len(self.log), type, payload or {})
        self.log.append(event)
        self.ctx.emit("session/event", event)
        return event

    @property
    def seq(self) -> int:
        """下一条事件的 seq（== 已记录事件数）。"""
        return len(self.log)

    def events(self) -> list[SessionEvent]:
        """返回事件快照（真实版返回只读视图）。"""
        return list(self.log)

    def __len__(self) -> int:
        return len(self.log)

    def __iter__(self):
        return iter(self.log)


class SessionStore:
    """会话注册表：create/get/list。经 ``ctx.sessions`` 访问。

    非 ``Service``（不构造即注册）：store 自身需在装配时由 workspace 显式
    ``ctx.provide("sessions", SessionStore(ctx))``，与 LLM/tools 等注册方式一致。
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self._sessions: dict[str, Session] = {}
        self._next_id = 0

    def create(self) -> Session:
        """创建一个新会话并登记。session_id = "session-0001" 式自增。"""
        self._next_id += 1
        session = Session(self.ctx, f"session-{self._next_id:04d}")
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list(self) -> list[Session]:
        return list(self._sessions.values())