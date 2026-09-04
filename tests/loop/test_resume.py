"""resume 验收测试：从事件流恢复会话（官方 AgentRegistry.resume + derive_messages）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.loop import AgentLoop, derive_messages
from minidsh.packages.services.prompt.providers.prompt import LocalSystemPromptService
from minidsh.packages.services.session import SessionStore, SessionEvent
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from minidsh.packages.services.llm.providers.openai import OpenAILlm
from tests.helpers.openai_fake import make_scripted_client
from tests.helpers.world import plug_execution_world
from minidsh.packages.tools import bash as tool_bash


def _assemble(script):
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    OpenAILlm(ctx, client=make_scripted_client(script), model="fake")
    LocalSystemPromptService(ctx)
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)
    return ctx, loop


# ---------- derive_messages（纯函数） ----------


def test_derive_messages_from_text_turns():
    events = [
        SessionEvent("s", 0, "user-message", {"text": "你好"}),
        SessionEvent("s", 1, "assistant-message", {"content": "在的", "stop_reason": "end-turn"}),
        SessionEvent("s", 2, "user-message", {"text": "继续"}),
    ]
    msgs = derive_messages(events)
    assert msgs == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在的"},
        {"role": "user", "content": "继续"},
    ]


def test_derive_messages_with_tool_roundtrip():
    events = [
        SessionEvent("s", 0, "user-message", {"text": "跑命令"}),
        SessionEvent("s", 1, "tool-call", {"name": "bash", "arguments": {"cmd": "echo hi"}, "call_id": "call-0"}),
        SessionEvent("s", 2, "tool-result", {"name": "bash", "result": "hi", "call_id": "call-0"}),
        SessionEvent("s", 3, "assistant-message", {"content": "完成", "stop_reason": "end-turn"}),
    ]
    msgs = derive_messages(events)
    assert msgs[0] == {"role": "user", "content": "跑命令"}
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["tool_calls"][0]["id"] == "call-0"
    assert msgs[2] == {"role": "tool", "tool_call_id": "call-0", "content": "hi"}
    assert msgs[3] == {"role": "assistant", "content": "完成"}


# ---------- resume ----------


async def test_resume_keeps_session_id_and_history():
    ctx, loop = _assemble([{"text": "恢复后回复"}])
    # 模拟已落盘事件
    events = [
        SessionEvent("session-0007", 0, "user-message", {"text": "旧问题"}),
        SessionEvent("session-0007", 1, "assistant-message", {"content": "旧答案", "stop_reason": "end-turn"}),
    ]
    agent = loop.resume("session-0007", events=events)

    # 沿用持久 session_id（不是重新计数）
    assert agent.session.id == "session-0007"
    # 历史消息已反投影
    assert agent.messages[0] == {"role": "user", "content": "旧问题"}
    assert agent.messages[1] == {"role": "assistant", "content": "旧答案"}

    # 接着聊：新的一轮正常跑
    agent.send("新问题")
    await agent.run()
    types = [e.type for e in agent.session]
    assert types.count("user-message") == 2
    assert types.count("assistant-message") == 2


async def test_resume_replays_history_then_continues():
    ctx, loop = _assemble([{"text": "接着答"}])
    events = [
        SessionEvent("session-0009", 0, "user-message", {"text": "第一问"}),
        SessionEvent("session-0009", 1, "assistant-message", {"content": "第一答", "stop_reason": "end-turn"}),
    ]
    agent = loop.resume("session-0009", events=events)
    agent.send("第二问")
    await agent.run()

    # 历史不重复广播（adopt 不重发 session/event）；事件流 = 旧 2 + 新
    # （turn/start + user + session/title + chunk + assistant-message + turn/end，M4/M7）
    assert len(agent.session) == 8
    am = [e for e in agent.session if e.type == "assistant-message"][-1]
    assert am.payload["content"] == "接着答"