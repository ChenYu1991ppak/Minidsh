"""SessionPersistence seam：会话持久化的「定义 + 协调器 + 适配器契约」。

源码对应（ch03 教学版，逐机制对齐）：
- ``SessionPersistence``      ↔ session-persistence/src/index.ts:84（Service Definition）
- ``PersistenceBackend``     ↔ session-persistence/src/coordinator.ts:127（存储适配器契约）
- ``PersistenceCoordinator`` ↔ coordinator.ts:588（installWritePath :1086、flush :1325、appendCore :682）
- ``WriteBehind``            ↔ session-persistence/src/write-behind.ts:22

分层理由（spec §9）：**seam（抽象）→ 协调器（缓冲/校验/边界），适配器（物理存储）**。
新增一个 provider = 新写一个 ``PersistenceBackend`` 子类，协调器与契约不变。

[教学简化] 相对 ch03：
- 无 ``turn/start``/``turn/end`` 结构事件；**刷盘边界 = ``assistant-message``**（v1 的「一条回复」边界），
  另提供 ``session/flush`` 事件作为显式屏障。
- 不做中断 turn 修复（interrupted-turn closer）——v1 的 compaction/重放不依赖 turn 结构。
- delay 写缓冲同步、flush-on-boundary；不引入 asyncio 定时器（loop 层异步在 T10 才出现，
  到那时若热路径确有解耦需要，再在此模块内改，仍不碰 seam 契约）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .event import SessionEvent

__all__ = [
    "SessionPersistence",
    "PersistenceBackend",
    "PersistenceCoordinator",
    "WriteBehind",
]

# 刷盘边界事件（v1 的「一条回复进、一条回复出」边界）
_FLUSH_BOUNDARY = "assistant-message"


# ---------------------------------------------------------------------------
# 一、seam 与适配器契约
# ---------------------------------------------------------------------------


class SessionPersistence(ABC):
    """持久化 Service Definition（session-persistence/src/index.ts:84）。

    契约三方法（真实版 11 个，此处收缩到核心）：
    - append：追加一批 **seq 连续** 的事件；首条 seq 必须等于已存 next-seq（:143）
    - load：冷读——从存储把会话读回（:183）；不存在返回 None
    - list：枚举已持久化的 session_id（:228）
    """

    @abstractmethod
    def append(self, session_id: str, events: list[SessionEvent]) -> None:
        """追加一批事件到存储。"""

    @abstractmethod
    def load(self, session_id: str) -> list[SessionEvent] | None:
        """冷读会话；不存在返回 None。"""

    @abstractmethod
    def list(self) -> list[str]:
        """枚举已持久化的 session_id 列表。"""


class PersistenceBackend(ABC):
    """存储适配器契约（PersistenceBackend，coordinator.ts:127）。

    [教学简化] 真实接口还有 locate/close；教学版保留 append_batch/load_stored/list 三个。
    """

    @abstractmethod
    def append_batch(self, session_id: str, events: list[SessionEvent]) -> None:
        """把一批事件写入存储。"""

    @abstractmethod
    def load_stored(self, session_id: str) -> list[SessionEvent] | None:
        """从存储读出事件列表；不存在返回 None。"""

    @abstractmethod
    def list(self) -> list[str]:
        """枚举已持久化的 session_id 列表。"""


# ---------------------------------------------------------------------------
# 二、协调器 + 延迟写缓冲
# ---------------------------------------------------------------------------


class WriteBehind:
    """延迟写缓冲（session-persistence/src/write-behind.ts:22）。

    事件先入队，flush 时整批取走。
    [教学简化] 真实版按周期批量 flush（默认 200ms）；教学版同步，用
    ``assistant-message`` 边界 + ``session/flush`` 屏障代替定时器。
    """

    def __init__(self):
        self.queue: list[SessionEvent] = []

    def enqueue(self, event: SessionEvent) -> None:
        self.queue.append(event)

    def take(self) -> list[SessionEvent]:
        batch, self.queue = self.queue, []
        return batch


class PersistenceCoordinator(SessionPersistence):
    """持久化协调器：事件流到磁盘的中枢（coordinator.ts:588）。

    写路径：订阅 ``session/event`` → 事件入 WriteBehind → 边界 flush 取批 →
    seq 连续校验 → backend.append_batch。读路径：load 委托 backend.load_stored。
    """

    def __init__(self, ctx, backend: PersistenceBackend):
        self.ctx = ctx
        self.backend = backend
        self.cursors: dict[str, int] = {}   # session_id → 已落盘最高 seq（cursor，appendCore :705-708）
        self.writes: dict[str, WriteBehind] = {}
        self._install_write_path()

    # 绑定名约定：workspace 以 ctx.provide("sessionPersistence", coordinator) 注册
    def _install_write_path(self):
        """订阅会话事件，把事件流引向磁盘（installWritePath，coordinator.ts:1086）。"""
        self.ctx.on("session/event", self._on_event)
        self.ctx.on("session/flush", self.flush)

    def _on_event(self, event: SessionEvent):
        """收到 session/event：入队；到达回合边界则刷盘。"""
        queue = self.writes.setdefault(event.session_id, WriteBehind())
        queue.enqueue(event)
        if event.type == _FLUSH_BOUNDARY:
            self.flush(event.session_id)

    def flush(self, session_id: str):
        """flush：取走队列全部事件、批量写盘（coordinator.ts:1325）。"""
        queue = self.writes.get(session_id)
        batch = queue.take() if queue else []
        if batch:
            self.append(session_id, batch)

    def append(self, session_id: str, events: list[SessionEvent]):
        """appendCore：seq 连续契约 + 事务性游标（coordinator.ts:682）。"""
        cursor = self.cursors.get(session_id, 0)
        for i, event in enumerate(events):
            if event.seq != cursor + i:
                raise ValueError(
                    f"append seq 断裂 {session_id!r}：期望 seq={cursor + i}，实际 {event.seq}"
                )
        self.backend.append_batch(session_id, events)      # 委托适配器写盘（:704）
        self.cursors[session_id] = cursor + len(events)    # 成功后才推进 cursor（:705-708）

    def load(self, session_id: str):
        """冷读：委托 backend.load_stored，并用落盘内容对齐游标（adopt :1036）。"""
        events = self.backend.load_stored(session_id)
        if events is None:
            return None
        if events:
            self.cursors[session_id] = len(events)
        return events

    def list(self):
        """枚举已持久化的会话（seam 契约 :228）。"""
        return self.backend.list()