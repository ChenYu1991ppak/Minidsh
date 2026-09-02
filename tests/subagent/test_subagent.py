"""T13 验收测试：subagent seam + in-process 派生子 loop。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.loop import AgentLoop
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.packages.services.subagent import (
    SubagentError,
    SubagentRegistry,
    InProcessSubagentProvider,
    make_task_tool,
)
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from minidsh.packages.tools import bash as tool_bash
from tests.helpers.world import plug_execution_world

from tests.helpers.fake_llm import make_fake_llm


def _assemble():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.plugin(make_fake_llm([{"text": "子代理回话"}]))
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    ctx.provide("agent_loop", AgentLoop(ctx))
    subagents = SubagentRegistry(ctx)
    ctx.provide("subagents", subagents)
    subagents.register_provider(InProcessSubagentProvider())
    return ctx, subagents, tools


# ---------- provider 注册 ----------


def test_register_and_list_providers():
    ctx, subagents, _ = _assemble()
    assert subagents.list_providers() == ["in-process"]


def test_duplicate_provider_rejected():
    ctx, subagents, _ = _assemble()
    with pytest.raises(SubagentError) as exc:
        subagents.register_provider(InProcessSubagentProvider())
    assert exc.value.code == "DUPLICATE_PROVIDER"


def test_unknown_provider():
    ctx, subagents, _ = _assemble()
    with pytest.raises(SubagentError) as exc:
        subagents.expect_provider("nope")
    assert exc.value.code == "UNKNOWN_PROVIDER"


# ---------- task 委派 ----------


async def test_task_returns_subagent_result():
    ctx, subagents, _ = _assemble()
    result = await subagents.task({"agent": {"name": "reviewer"}, "task": "审查代码"})
    assert result.text == "子代理回话"


async def test_child_session_is_independent():
    ctx, subagents, tools = _assemble()
    parent_ids_before = {s.id for s in ctx.sessions.list()}

    result = await subagents.task({"agent": {"name": "reviewer"}, "task": "t"})
    assert result.text == "子代理回话"

    after = ctx.sessions.list()
    assert len(after) == len(parent_ids_before) + 1  # 多一个子会话
    assert all(s.id.startswith("session-") for s in after)


async def test_max_depth_exceeded():
    ctx, subagents, _ = _assemble()
    # 深度来自父会话 origin.depth（不信任调用方传值）：把父会话挂到运行栈
    parent = ctx.sessions.create()
    parent.origin = {"agent": "root", "depth": 5}
    ctx._session_stack = [parent]
    with pytest.raises(SubagentError) as exc:
        await subagents.task({"agent": "a", "task": "t", "max_depth": 3})
    assert exc.value.code == "MAX_DEPTH"


# ---------- task 工具 ----------


async def test_task_tool_delegates():
    ctx, subagents, tools = _assemble()
    tool = make_task_tool(subagents)
    tools.register(tool)

    result = await tools.execute(
        ToolExecution("c1", "task", {"agent": "reviewer", "task": "帮我审查"})
    )
    assert "reviewer 返回" in result.content
    assert "子代理回话" in result.content


# ---------- 跨层桥接：task 工具在父会话记录 spawn/result ----------


async def test_task_tool_records_spawn_result_on_parent():
    ctx, subagents, tools = _assemble()
    tools.register(make_task_tool(subagents))

    parent = ctx.sessions.create()
    # 模拟 loop 运行栈：把父会话压栈
    ctx._session_stack = [parent]

    await tools.execute(
        ToolExecution("c1", "task", {"agent": "reviewer", "task": "审查"})
    )

    types = [e.type for e in parent]
    assert types == ["subagent-spawn", "subagent-result"]