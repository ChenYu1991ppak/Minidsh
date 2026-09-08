"""agents 模块：ctx.agents 独立注册表 + Agent 公开手柄 + factory 接口。

源码对应：packages/core/agent/src/index.ts（AgentRegistry）、types.ts（Agent）。

关键机制（core.zh.md）：
- ``ctx.agents`` 是**注册表**（track 存活 agent + 携带发起者），agent **创建**由实现了
  ``AgentFactory`` 的插件（loop）经 ``setFactory`` 注册——消费方用 ``ctx.agents`` 时
  不依赖具体 loop 包 → loop 可替换。
- ``AgentHandle`` 的 disposer 是能力：只有创建它的消费方持有它；
- initiator scope：当前驱动的 ``Agent`` 作为进程内发起者，经 ``withInitiator()`` 携带。

三角色：``AgentRegistry`` 是能力边界 provider（提供 ctx.agents 服务）；
``AgentFactory`` 是「创建接口」；loop 是唯一的工厂实现（M9 接入）。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable

from minidsh.cordis import CapabilityProvider

__all__ = [
    "Agent",
    "AgentHandle",
    "AgentFactory",
    "AgentRegistry",
]


class Agent:
    """公开存活 agent 手柄（types.ts Agent）。具体实现为 loop 包内部细节。"""

    def __init__(self, agent_id: str, session=None, options: dict | None = None,
                 scoped_ctx=None):
        self.id = agent_id
        self.session = session
        self.options = options or {}
        self.scoped_ctx = scoped_ctx     # agent-scoped 上下文（M7/M9 接 scope）
        self.status = "idle"

    def send(self, message, target=None, wakeup: bool = True) -> None:
        """把一条输入路由到 inbox 边界（types.ts send）。具体驱动由并发实现。"""
        raise NotImplementedError


class AgentHandle:
    """归属创建方的「agent + disposer」（types.ts AgentHandle）。

    ``dispose()`` 停 loop、注销、移除会话、回滚 scoped 世界；disposer 是能力，
    只暴露给创建它的 owner。
    """

    def __init__(self, agent: Agent, dispose: Callable[[], None]):
        self.agent = agent
        self._dispose = dispose

    def dispose(self) -> None:
        if self._dispose is not None:
            d, self._dispose = self._dispose, None
            d()


class AgentFactory:
    """创建接口（types.ts AgentFactory）：createAgent / resumeAgent。loop 实现之。"""

    async def create_agent(self, owner_ctx, options: dict) -> AgentHandle:
        raise NotImplementedError

    async def resume_agent(self, owner_ctx, options: dict) -> AgentHandle:
        raise NotImplementedError


class AgentRegistry(CapabilityProvider):
    """ctx.agents：track 存活 agent + 携带发起者 + 委托 factory 创建（index.ts）。"""

    service_name = "agents"

    def _init(self, ctx):
        self._live: dict[str, Agent] = {}
        self._factory: AgentFactory | None = None
        self._initiator_stack: list[Agent] = []

    # ---------- factory ----------

    def set_factory(self, factory: AgentFactory) -> Callable[[], None]:
        """注册创建接口；覆盖旧 factory；返回卸载 disposer（index.ts setFactory）。"""
        self._factory = factory

        def dispose():
            if self._factory is factory:
                self._factory = None

        return self.ctx.effect(lambda: dispose, label="agents:factory")

    # ---------- 创建 / 恢复 ----------

    async def create(self, options: dict | None = None,
                     owner_ctx=None) -> AgentHandle:
        """经 factory 创建 agent（index.ts create）。"""
        if self._factory is None:
            raise RuntimeError("ctx.agents 未设置 factory（loop 未装配）")
        owner = owner_ctx if owner_ctx is not None else self.ctx
        handle = await self._factory.create_agent(owner, options or {})
        self._publish(handle.agent)
        return handle

    async def resume(self, options: dict | None = None,
                     owner_ctx=None) -> AgentHandle:
        """经 factory 恢复持久会话上的 agent（index.ts resume）。"""
        if self._factory is None:
            raise RuntimeError("ctx.agents 未设置 factory（loop 未装配）")
        owner = owner_ctx if owner_ctx is not None else self.ctx
        handle = await self._factory.resume_agent(owner, options or {})
        self._publish(handle.agent)
        return handle

    # ---------- 发布 / 查询 ----------

    def _publish(self, agent: Agent) -> None:
        """登记存活 agent 并广播 agent/created。"""
        self._live[agent.id] = agent
        self.ctx.emit("agent/created", {"id": agent.id, "agent": agent})

    def _unpublish(self, agent_id: str) -> None:
        if agent_id in self._live:
            agent = self._live.pop(agent_id)
            self.ctx.emit("agent/disposed", {"id": agent_id, "agent": agent})

    def register_live(self, agent: Agent) -> Callable[[], None]:
        """供 factory 直接把建好的 agent 登记进来，返回注销 disposer。"""
        self._publish(agent)

        def dispose():
            self._unpublish(agent.id)

        return self.ctx.effect(lambda: dispose, label=f"agent:{agent.id}")

    def get(self, agent_id: str) -> Agent | None:
        return self._live.get(agent_id)

    def list(self) -> list[Agent]:
        return list(self._live.values())

    # ---------- 发起者 scope ----------

    @property
    def initiator(self) -> Agent | None:
        """当前进程内发起者（types.ts initiator）。None = 无发起中 agent。"""
        return self._initiator_stack[-1] if self._initiator_stack else None

    @contextmanager
    def with_initiator(self, agent: Agent):
        """在 ``agent`` 作为发起者的作用域内运行（types.ts withInitiator 的同步化）。"""
        self._initiator_stack.append(agent)
        try:
            yield agent
        finally:
            self._initiator_stack.pop()