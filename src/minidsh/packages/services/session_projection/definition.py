"""sessionProjections 模块：从 append-only 事件日志折叠只读状态（ctx.sessionProjections）。

源码对应：packages/session/session-projection/src/index.ts。

核心机制（framework drives, domain computes）：
- registry 订阅一次 ``session/event``，把每条已提交事件过所有单元 ``apply``（eager drive）；
- 单元是纯同步 fold（``init`` + ``apply`` + ``stateVersion`` + 可选 ``wire``）；
- ``apply`` **引用不变 = 零下游工作**；
- cells 惰性构建（晚注册单元 / 早于 registry 的会话，首次触达时 init 折叠内存日志）；
- 注册是 effect（disposer 随 fiber 卸载）；重复 key + 不同 stateVersion 抛错。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from minidsh.cordis import CapabilityProvider

__all__ = [
    "ProjectionDefinition",
    "ProjectionSnapshot",
    "SessionProjectionRegistry",
]


@dataclass(frozen=True)
class ProjectionDefinition:
    """一个领域的纯同步折叠单元（官方 ProjectionDefinition）。

    - ``key``：该单元拥有的状态键；
    - ``state_version``：持久缓存失效版本号，语义变则 +1；
    - ``init(header)``：空日志的初始状态（入参 header = SessionHeader）；
    - ``apply(state, event)``：旧状态 + 一条事件 → 新状态；不感兴趣必须返回原引用；
    - ``wire``（可选）``(state) -> value``：把状态转成客户可见的整值视图。
    """

    key: str
    init: Callable[[Any], Any]
    apply: Callable[[Any, Any], Any]
    state_version: int = 1
    wire: Callable[[Any], Any] | None = None


@dataclass(frozen=True)
class ProjectionSnapshot:
    """一致读切面（官方 ProjectionSnapshot）：所有值反映到同一条 seq 为止。"""

    as_of_seq: int
    values: dict


class SessionProjectionRegistry(CapabilityProvider):
    """ctx.sessionProjections：驱动事件流过所有已注册单元，提供快照/单键读。"""

    service_name = "sessionProjections"

    def _init(self, ctx):
        self._units: dict[str, ProjectionDefinition] = {}
        self._unit_count: dict[str, int] = {}
        # session_id → {key: (watermark_seq, state)}
        self._cells: dict[str, dict[str, list]] = {}
        self._listeners: list[Callable] = []
        ctx.on("session/event", self._on_event)

    # ---------- 注册 ----------

    def register(self, definition: ProjectionDefinition) -> Callable[[], None]:
        key = definition.key
        existing = self._units.get(key)
        if existing is not None:
            if existing.state_version != definition.state_version:
                raise ValueError(
                    f"重复投影 key {key!r} 但 stateVersion 不同 "
                    f"({existing.state_version} vs {definition.state_version})"
                )
            # 同版本：共享一个单元并计数（卸载最后一个才移除）
            self._unit_count[key] = self._unit_count.get(key, 1) + 1
            return self._make_disposer(key)
        self._units[key] = definition
        self._unit_count[key] = 1
        return self._make_disposer(key)

    def _make_disposer(self, key: str) -> Callable[[], None]:
        def dispose():
            if key not in self._units:
                return
            self._unit_count[key] -= 1
            if self._unit_count[key] <= 0:
                self._units.pop(key, None)
                self._unit_count.pop(key, None)
                for cells in self._cells.values():
                    cells.pop(key, None)

        return self.ctx.effect(lambda: dispose, label=f"projection:{key}")

    # ---------- 驱动 ----------

    def _on_event(self, event):
        session_id = event.session_id
        for key, unit in self._units.items():
            cell = self._cell_for(session_id, key, unit)
            prev_state = cell[1]
            next_state = unit.apply(prev_state, event)
            if next_state is prev_state:
                continue  # 引用不变 = 零下游工作
            cell[0] = event.seq
            cell[1] = next_state
            if unit.wire is not None:
                value = unit.wire(next_state)
                for listener in list(self._listeners):
                    listener(session_id, key, value, event.seq)

    def _cell_for(self, session_id: str, key: str, unit: ProjectionDefinition) -> list:
        """取（必要时惰性构建）某 session 的某单元 cell；新 cell 先 init 折叠内存日志。"""
        session_cells = self._cells.setdefault(session_id, {})
        if key not in session_cells:
            cell = self._fold_init(session_id, unit)
            session_cells[key] = cell
        return session_cells[key]

    def _fold_init(self, session_id: str, unit: ProjectionDefinition) -> list:
        """init 后把已存在的内存日志折叠到当前水位（懒构建：registries 晚于事件流）。"""
        sessions = self.ctx.probe("sessions")
        session = sessions.get(session_id)
        header = session.header if session is not None else None
        state = unit.init(header)
        watermark = -1
        if session is not None:
            for event in session.events():
                next_state = unit.apply(state, event)
                if next_state is not state:
                    state = next_state
                    watermark = event.seq
        return [watermark, state]

    # ---------- 读 ----------

    def snapshot(self, session) -> ProjectionSnapshot:
        """一致读切面：所有已注册 wire 单元的整值 + 共享 asOfSeq。"""
        values: dict = {}
        as_of_seq = -1
        for key, unit in self._units.items():
            if unit.wire is None:
                continue
            cell = self._cell_for(session.id, key, unit)
            values[key] = unit.wire(cell[1])
            as_of_seq = max(as_of_seq, cell[0])
        return ProjectionSnapshot(as_of_seq=as_of_seq, values=values)

    def state_of(self, session, key: str):
        """单键读：某 session 某单元的折叠状态（host 侧读取）。"""
        unit = self._units.get(key)
        if unit is None:
            raise KeyError(f"投影 key 未注册：{key!r}")
        cell = self._cell_for(session.id, key, unit)
        return cell[1]

    # ---------- 变更馈送 ----------

    def on_change(self, listener: Callable) -> Callable[[], None]:
        """注册变更监听（client-visible 单元的 state 引用变了才通知一次）。"""
        self._listeners.append(listener)

        def dispose():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return self.ctx.effect(lambda: dispose, label="projection:change-feed")


# ---------------------------------------------------------------------------
# 真实投影单元：lastMessage（供 subagent 读 final，M9）
# ---------------------------------------------------------------------------


def make_last_message_unit() -> ProjectionDefinition:
    """折叠最后一条 assistant-message → {content, seq}。"""

    initial = {"content": "", "seq": -1}

    def init(header):
        return dict(initial)

    def apply(state, event):
        if event.type == "assistant-message":
            return {"content": event.payload.get("content", ""), "seq": event.seq}
        return state  # 无关事件：返回原引用

    def wire(state):
        return dict(state)

    return ProjectionDefinition(key="lastMessage", init=init, apply=apply, wire=wire)