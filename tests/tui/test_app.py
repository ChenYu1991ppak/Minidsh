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