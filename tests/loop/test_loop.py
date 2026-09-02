"""T10 验收测试：AgentLoop + Inbox + react 决策。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.loop import AgentLoop, Inbox, ReactLoopAgent
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from minidsh.packages.tools import bash as tool_bash
from tests.helpers.world import plug_execution_world

from tests.helpers.fake_llm import make_fake_llm


def _assemble(script=None):
    """装配完整能力图：session + llm(openai 假 client) + prompt + tools(bash) + loop。

    script 按「轮次」回放：``[{"text": ...}]`` 或 ``[{"tool_calls": [(name, args, id), ...]}, ...]``。
    """
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    ctx.plugin(make_fake_llm(script))
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)
    return ctx, loop


# ---------- Inbox ----------


def test_inbox_enqueue_claim_clears():
    box = Inbox()
    box.enqueue({"role": "user", "content": "a"})
    box.enqueue({"role": "user", "content": "b"})
    assert box.has_pending is True
    claimed = box.claim()
    assert [m["content"] for m in claimed] == ["a", "b"]
    assert box.has_pending is False


# ---------- AgentLoop.create ----------


def test_create_returns_agent_and_broadcasts():
    ctx, loop = _assemble([{"text": "hi"}])
    seen = []
    ctx.on("agent/session-start", lambda ev: seen.append(ev["session_id"]))
    agent = loop.create()

    assert agent is not None
    assert agent.session.id == "session-0001"
    assert loop.get(agent.session.id) is agent
    assert seen == ["session-0001"]


# ---------- react：文本闭环 ----------


async def test_text_turn_produces_closed_loop_events():
    ctx, loop = _assemble([{"text": "你好"}])
    agent = loop.create()
    agent.send("问候")

    await agent.run()

    types = [e.type for e in agent.session]
    assert types[0] == "user-message"
    assert "assistant-chunk" in types
    assert types[-1] == "assistant-message"
    assert agent.session.events()[-1].payload["content"] == "你好"
    assert agent.session.events()[-1].payload["stop_reason"] == "end-turn"


# ---------- react：工具调用闭环 ----------


async def test_tool_call_roundtrip():
    script = [
        {"tool_calls": [("bash", '{"cmd":"echo hi"}', "call-0")]},
        {"text": "完成"},
    ]
    ctx, loop = _assemble(script)
    agent = loop.create()
    agent.send("跑一条命令")

    await agent.run()

    types = [e.type for e in agent.session]
    # 完整事件序列：user → tool-call → tool-result → assistant-*（文本收尾）
    assert types == [
        "user-message",
        "tool-call",
        "tool-result",
        "assistant-chunk",
        "assistant-message",
    ]
    tc = agent.session.events()[1]
    assert tc.payload["name"] == "bash"
    tr = agent.session.events()[2]
    assert "hi" in tr.payload["result"]
    assert tr.payload["is_error"] is False
    assert agent.session.events()[-1].payload["content"] == "完成"


async def test_tool_arguments_parsed_to_dict():
    """JSON 参数解析：arguments 字符串 → dict，供 guard/execute 使用。"""
    script = [
        {"tool_calls": [("bash", '{"cmd": "echo hi"}', "call-0")]},
        {"text": "ok"},
    ]
    ctx, loop = _assemble(script)
    agent = loop.create()
    agent.send("x")
    await agent.run()
    tc = [e for e in agent.session if e.type == "tool-call"][0]
    assert tc.payload["arguments"] == {"cmd": "echo hi"}


async def test_multiple_react_steps_until_text():
    """连续两轮工具调用，第三轮才给文本。"""
    script = [
        {"tool_calls": [("bash", '{"cmd":"a"}', "call-0")]},
        {"tool_calls": [("bash", '{"cmd":"b"}', "call-1")]},
        {"text": "done"},
    ]
    ctx, loop = _assemble(script)
    agent = loop.create()
    agent.send("连调两次")

    await agent.run()

    types = [e.type for e in agent.session]
    assert types.count("tool-call") == 2
    assert types.count("tool-result") == 2
    assert types[-1] == "assistant-message"


# ---------- 参数解析边界 ----------


def test_parse_arguments_garbage_yields_raw():
    from minidsh.packages.services.loop.agent_loop import _parse_arguments

    assert _parse_arguments("{not json") == {"_raw": "{not json"}
    assert _parse_arguments(None) == {}
    assert _parse_arguments('{"a": 1}') == {"a": 1}