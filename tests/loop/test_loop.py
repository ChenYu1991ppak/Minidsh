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
    # M4：turn/start 开、turn/end 收；user-message/assistant-message 在其间
    assert types[0] == "turn/start"
    assert types[-1] == "turn/end"
    assert "assistant-chunk" in types
    am = [e for e in agent.session if e.type == "assistant-message"][-1]
    assert am.payload["content"] == "你好"
    assert am.payload["stop_reason"] == "end-turn"


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
    # M4/M7：turn/start → user → session/title → tool-call → tool-result → assistant-* → turn/end
    assert types == [
        "turn/start",
        "user-message",
        "session/title",
        "tool-call",
        "tool-result",
        "assistant-chunk",
        "assistant-message",
        "turn/end",
    ]
    tc = agent.session.events()[3]
    assert tc.payload["name"] == "bash"
    tr = agent.session.events()[4]
    assert "hi" in tr.payload["result"]
    assert tr.payload["is_error"] is False
    am = agent.session.events()[-2]  # turn/end 前一条是 assistant-message
    assert am.payload["content"] == "完成"


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
    assert types[-1] == "turn/end"          # M4：末事件是 turn/end
    assert types[-2] == "assistant-message"  # turn/end 前是文本收尾


# ---------- 参数解析边界 ----------


def test_parse_arguments_garbage_yields_raw():
    from minidsh.packages.services.loop.agent_loop import _parse_arguments

    assert _parse_arguments("{not json") == {"_raw": "{not json"}
    assert _parse_arguments(None) == {}
    assert _parse_arguments('{"a": 1}') == {"a": 1}


# ---------- M4 turn 边界 + surface 分层 ----------


async def test_turn_boundary_events_pair():
    """一轮对话产 turn/start + turn/end 配对，turn 号递增。"""
    ctx, loop = _assemble([{"text": "A"}, {"text": "B"}])
    agent = loop.create()
    agent.send("第一问")
    await agent.run()
    agent.send("第二问")
    await agent.run()

    starts = [e for e in agent.session if e.type == "turn/start"]
    ends = [e for e in agent.session if e.type == "turn/end"]
    assert len(starts) == 2
    assert len(ends) == 2
    assert [e.payload["turn"] for e in starts] == [1, 2]
    assert [e.payload["turn"] for e in ends] == [1, 2]
    # 正常收尾 → completed
    assert all(e.payload["reason"]["kind"] == "completed" for e in ends)


async def test_turn_events_are_audit_surface():
    """turn/start、turn/end、session/title 是审计面事件（surface=False）。"""
    from minidsh.packages.services.session.event import AUDIT_TYPES

    ctx, loop = _assemble([{"text": "x"}])
    agent = loop.create()
    agent.send("q")
    await agent.run()
    for e in agent.session:
        if e.type in AUDIT_TYPES:
            assert e.surface is False
        else:
            assert e.surface is True


def test_derive_messages_skips_audit_events():
    """derive_messages 显式跳过审计事件（turn/*、session/title）。"""
    from minidsh.packages.services.loop.agent_loop import derive_messages
    from minidsh.packages.services.session import SessionEvent

    events = [
        SessionEvent("s", 0, "turn/start", {"turn": 1}),
        SessionEvent("s", 1, "user-message", {"text": "hi"}),
        SessionEvent("s", 2, "assistant-message", {"content": "yo", "stop_reason": "end-turn"}),
        SessionEvent("s", 3, "turn/end", {"turn": 1, "reason": {"kind": "completed"}}),
        SessionEvent("s", 4, "session/title", {"title": "hi"}),
    ]
    msgs = derive_messages(events)
    # turn/*、session/title 是审计面，不进模型消息
    assert msgs == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]


async def test_turn_end_error_on_max_steps():
    """max react steps 超限 → turn/end reason=error。"""
    from minidsh.packages.services.loop.agent_loop import _MAX_REACT_STEPS

    # 剧本恒产工具调用 → 用尽后回放最后一行，触顶 _MAX_REACT_STEPS
    script = [{"tool_calls": [("bash", '{"cmd":"loop"}', "call-0")]}]
    ctx, loop = _assemble(script)
    agent = loop.create()
    agent.send("死循环")
    await agent.run()

    ends = [e for e in agent.session if e.type == "turn/end"]
    assert len(ends) == 1
    assert ends[0].payload["reason"]["kind"] == "error"
    # 且产了一条 error 事件
    assert any(e.type == "error" for e in agent.session)


async def test_resume_recovers_turn_no():
    """resume 后从历史 turn/start 恢复 turn 号，续聊不重头。"""
    from minidsh.packages.services.session import SessionEvent

    ctx, loop = _assemble([{"text": "新回复"}])
    # 已落盘：两轮历史（turn 1、turn 2）
    events = [
        SessionEvent("session-0042", 0, "turn/start", {"turn": 1}),
        SessionEvent("session-0042", 1, "user-message", {"text": "q1"}),
        SessionEvent("session-0042", 2, "assistant-message", {"content": "a1", "stop_reason": "end-turn"}),
        SessionEvent("session-0042", 3, "turn/end", {"turn": 1, "reason": {"kind": "completed"}}),
        SessionEvent("session-0042", 4, "turn/start", {"turn": 2}),
        SessionEvent("session-0042", 5, "user-message", {"text": "q2"}),
        SessionEvent("session-0042", 6, "assistant-message", {"content": "a2", "stop_reason": "end-turn"}),
        SessionEvent("session-0042", 7, "turn/end", {"turn": 2, "reason": {"kind": "completed"}}),
    ]
    agent = loop.resume("session-0042", events=events)
    agent.send("q3")
    await agent.run()

    starts = [e for e in agent.session if e.type == "turn/start"]
    # 新轮是 turn 3（续接，不重头）
    assert [e.payload["turn"] for e in starts] == [1, 2, 3]


# ---------- M7 session title fallback ----------


def test_fallback_session_title_basic():
    from minidsh.packages.services.loop.agent_loop import fallback_session_title

    assert fallback_session_title("hello world") == "hello world"


def test_fallback_session_title_control_chars():
    from minidsh.packages.services.loop.agent_loop import fallback_session_title

    assert "\x1b" not in fallback_session_title("hello\x1b\x00world")
    assert "hello" in fallback_session_title("hello\x1b\x00world")


def test_fallback_session_title_truncates_words():
    from minidsh.packages.services.loop.agent_loop import fallback_session_title

    many = " ".join("word" for _ in range(20))
    result = fallback_session_title(many, max_words=8)
    assert len(result.split()) <= 8


def test_fallback_session_title_truncates_bytes():
    from minidsh.packages.services.loop.agent_loop import fallback_session_title

    long = "这是一个很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长的标题"
    result = fallback_session_title(long, max_words=100, max_bytes=30)
    assert len(result.encode("utf-8")) <= 30


def test_fallback_session_title_empty():
    from minidsh.packages.services.loop.agent_loop import fallback_session_title

    assert fallback_session_title("") == ""
    assert fallback_session_title("   ") == ""


async def test_session_title_event_produced_on_first_message():
    """首条 user-message 产 session/title 事件（确定性 fallback）。"""
    ctx, loop = _assemble([{"text": "回复"}])
    agent = loop.create()
    agent.send("帮我写代码")
    await agent.run()

    titles = [e for e in agent.session if e.type == "session/title"]
    assert len(titles) == 1
    assert titles[0].payload["title"] is not None
    assert "帮我写代码" in titles[0].payload["title"]


async def test_session_title_skipped_by_derive_messages():
    """session/title 是审计面（surface=False），derive_messages 跳过。"""
    from minidsh.packages.services.loop.agent_loop import derive_messages
    from minidsh.packages.services.session import SessionEvent

    events = [
        SessionEvent("s", 0, "session/title", {"title": "test"}),
        SessionEvent("s", 1, "user-message", {"text": "hi"}),
    ]
    msgs = derive_messages(events)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"