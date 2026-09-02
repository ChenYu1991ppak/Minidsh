"""M2 验收测试：ctx.agents 注册表 + factory 创建 + initiator scope。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.agents import Agent, AgentFactory, AgentRegistry


class _FakeFactory(AgentFactory):
    """测试用 factory：create/resume 直接烘一个 Agent。"""

    def __init__(self):
        self.created = []
        self.resumed = []

    async def create_agent(self, owner_ctx, options: dict) -> "object":
        agent = Agent(agent_id=f"a-{len(self.created)}", options=options)
        self.created.append(agent)
        return _SimpleHandle(agent)

    async def resume_agent(self, owner_ctx, options: dict):
        agent = Agent(agent_id=f"r-{len(self.resumed)}", options=options)
        self.resumed.append(agent)
        return _SimpleHandle(agent)


class _SimpleHandle:
    def __init__(self, agent):
        self.agent = agent

    def dispose(self):
        pass


def _ctx_with_factory():
    ctx = Context()
    registry = AgentRegistry(ctx)
    ctx.provide("agents", registry)
    factory = _FakeFactory()
    registry.set_factory(factory)
    return ctx, registry, factory


# ---------- factory 注册与创建 ----------


async def test_create_delegates_to_factory():
    ctx, registry, factory = _ctx_with_factory()
    handle = await registry.create({"model": "x"})
    assert handle.agent.id == "a-0"
    assert registry.get("a-0") is handle.agent
    assert registry.list() == [handle.agent]


async def test_create_without_factory_raises():
    ctx = Context()
    registry = AgentRegistry(ctx)
    with pytest.raises(RuntimeError):
        await registry.create({})


async def test_resume_delegates_to_factory():
    ctx, registry, factory = _ctx_with_factory()
    handle = await registry.resume({"session_id": "s"})
    assert handle.agent.id == "r-0"


def test_set_factory_replaced():
    ctx = Context()
    registry = AgentRegistry(ctx)
    a = _FakeFactory()
    b = _FakeFactory()
    registry.set_factory(a)
    registry.set_factory(b)
    assert registry._factory is b


# ---------- 发布 / 注销 ----------


def test_register_live_and_dispose_broadcast():
    ctx = Context()
    registry = AgentRegistry(ctx)
    seen = []
    ctx.on("agent/created", lambda e: seen.append(e["id"]))
    ctx.on("agent/disposed", lambda e: seen.append(("d", e["id"])))

    agent = Agent("a-1")
    disp = registry.register_live(agent)
    assert registry.get("a-1") is agent
    disp()
    assert registry.get("a-1") is None
    assert seen == ["a-1", ("d", "a-1")]


# ---------- initiator scope ----------


def test_initiator_none_by_default():
    ctx = Context()
    registry = AgentRegistry(ctx)
    assert registry.initiator is None


def test_with_initiator_carries_agent():
    ctx = Context()
    registry = AgentRegistry(ctx)
    parent = Agent("parent")
    with registry.with_initiator(parent):
        assert registry.initiator is parent
    assert registry.initiator is None  # 嵌套退栈


def test_with_initiator_nested():
    ctx = Context()
    registry = AgentRegistry(ctx)
    outer = Agent("outer")
    inner = Agent("inner")
    with registry.with_initiator(outer):
        with registry.with_initiator(inner):
            assert registry.initiator is inner
        assert registry.initiator is outer