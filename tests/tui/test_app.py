"""T2/T3 验收测试：TUI App + bridge（Textual Pilot + 事件驱动）。

无终端环境由 Textual headless 支持，跑真实 App 生命周期。
"""
from __future__ import annotations

import asyncio

import pytest

from minidsh.cordis import Context
from minidsh.packages.services.session import SessionStore
from minidsh.infrastructure.tui.app import TuiApp
from minidsh.infrastructure.tui.bridge import subscribe, EventMessage
from minidsh.infrastructure.tui.transcript import fold


# ---------- T3 bridge（无 Textual） ----------


class _Recorder:
    def __init__(self):
        self.messages = []

    def post_message(self, msg):
        self.messages.append(msg)


def test_subscribe_forwards_events_as_messages():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    rec = _Recorder()
    subscribe(ctx, rec.post_message)

    session = ctx.sessions.create()
    session.append("user-message", {"text": "hi"})
    session.append("assistant-message", {"content": "yo", "stop_reason": "end-turn"})

    assert len(rec.messages) == 2
    assert isinstance(rec.messages[0], EventMessage)
    assert rec.messages[0].event.type == "user-message"


async def test_drive_serial_runs_agent():
    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    queue = asyncio.Queue()

    events = []

    class _Agent:
        session = ctx.sessions.create()
        running = []

        def send(self, text):
            self.running.append(("send", text))

        async def run(self):
            self.running.append(("run",))
            self.session.append("assistant-message", {"content": "done", "stop_reason": "end-turn"})

    agent = _Agent()
    await queue.put("你好")
    await queue.put("再见")
    await queue.put(None)  # 哨兵

    from minidsh.infrastructure.tui.bridge import drive

    await drive(agent, queue, ctx)

    assert agent.running == [("send", "你好"), ("run",), ("send", "再见"), ("run",)]


# ---------- T2 App（Textual Pilot） ----------


@pytest.mark.asyncio
async def test_app_renders_turns_on_event():
    from textual.app import App

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    # on_mount 里读 ctx.llm.reasoning_effort → 需提供一个 llm
    ctx.provide("llm", type("Llm", (), {"reasoning_effort": "medium", "model": "fake"})())
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        # 直接投递两条事件消息 → on_event_message 更新转录 widget
        session.append("user-message", {"text": "嗨"})
        session.append("assistant-message", {"content": "回你", "stop_reason": "end-turn"})
        await pilot.pause()

        transcript = app.query_one("#transcript")
        assert "### 你" in transcript.content
        assert "### assistant" in transcript.content
        assert "回你" in transcript.content
        # 状态栏显示了会话 id
        assert session.id in app.query_one("#status-label").content


# ---------- M4 斜杠命令（/model /thinking） ----------


class _FakeLlm:
    """可 reconfigure 的假 llm，记录切模型/切档位调用。"""

    def __init__(self):
        self.model = "demo-a"
        self.reasoning_effort = "medium"
        self.reconfigs = []

    def reconfigure(self, spec):
        self.reconfigs.append(spec)
        self.model = spec.id
        self.reasoning_effort = spec.reasoning_effort


class _FakeConfig:
    def __init__(self, models):
        self.models = {m["id"]: type("Spec", (), m)() for m in models}
        self._current = self.models[models[0]["id"]]

    def find(self, model_id):
        return self.models.get(model_id)

    @property
    def current(self):
        return self._current


@pytest.mark.asyncio
async def test_model_slash_command_reconfigures_and_keeps_session():
    from textual.widgets import Input

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    config = _FakeConfig([
        {"id": "demo-a", "url": "u", "reasoning_effort": "medium"},
        {"id": "demo-b", "url": "u2", "reasoning_effort": "high"},
    ])
    ctx.provide("llm", llm)
    ctx.provide("config", config)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        inp = app.query_one("#input", Input)
        inp.focus()
        await pilot.press(*"/model demo-b", "enter")
        await pilot.pause()

        assert llm.reconfigs[-1].id == "demo-b"
        assert llm.model == "demo-b"
        # 同会话续聊：会话没换
        assert app.agent.session is session
        # model-change 事件已记录
        assert session.events()[-1].type == "model-change"
        # 状态栏更新为 demo-b
        assert "demo-b" in app.query_one("#status-label").content


@pytest.mark.asyncio
async def test_resume_seeds_history_into_transcript():
    """重启恢复：历史事件经 mount seed 进转录（否则重启后空白）。"""
    from minidsh.packages.services.session import SessionEvent

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session
    # 预置历史事件（模拟 resume 后的会话）
    session.log = [
        SessionEvent(session.id, 0, "user-message", {"text": "旧问题"}),
        SessionEvent(session.id, 1, "assistant-message", {"content": "旧答案", "stop_reason": "end-turn"}),
    ]

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        await pilot.pause()
        transcript = app.query_one("#transcript")
        assert "旧问题" in transcript.content
        assert "旧答案" in transcript.content


@pytest.mark.asyncio
async def test_thinking_slash_command_reconfigures_effort():
    from textual.widgets import Input

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    config = _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}])
    ctx.provide("config", config)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        inp = app.query_one("#input", Input)
        inp.focus()
        await pilot.press(*"/thinking high", "enter")
        await pilot.pause()

        assert llm.reasoning_effort == "high"
        assert session.events()[-1].type == "model-change"
        assert "high" in app.query_one("#status-label").content


@pytest.mark.asyncio
async def test_thinking_invalid_level_rejected():
    from textual.widgets import Input

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    config = _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}])
    ctx.provide("config", config)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        inp = app.query_one("#input", Input)
        inp.focus()
        await pilot.press(*"/thinking ultra", "enter")
        await pilot.pause()

        # 非法档位：强度不变，报错提示
        assert llm.reasoning_effort == "medium"
        assert "非法档位" in app.query_one("#transcript").content