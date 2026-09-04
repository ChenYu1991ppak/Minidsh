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
async def test_new_session_switches_agent_without_exit():
    """/new 切换新 agent，进程保持（不 exit），转录清空。"""
    from textual.widgets import Input

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    # 需要一个 agent_loop 服务供 /new 调 create
    from minidsh.packages.services.loop import AgentLoop
    loop = AgentLoop(ctx)
    ctx.provide("agent_loop", loop)

    start_agent = loop.create()
    app = TuiApp(ctx, start_agent)
    async with app.run_test() as pilot:
        inp = app.query_one("#input", Input)
        inp.focus()
        await pilot.press(*"/new", "enter")
        await pilot.pause()

        assert app.agent is not start_agent        # 换了新 agent
        assert app.agent.session.id != start_agent.session.id
        assert app._events == []                   # 转录清空
        # 进程未退出（app 仍在运行）
        assert app.is_running


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


# ---------- M3 命令注册表 ----------


def test_command_registry_dispatch_and_fallback():
    from minidsh.infrastructure.tui.commands import Command, CommandRegistry

    reg = CommandRegistry()
    calls = []

    async def _h(app, arg):
        calls.append(("hello", arg))

    reg.register(Command("hello", "打招呼", _h))

    async def _run():
        assert await reg.dispatch(None, "/hello world") is True
        assert calls == [("hello", "world")]
        # 未注册命令 → False（调用方降级为消息）
        assert await reg.dispatch(None, "/unknown x") is False
        # 非 / 开头 → False
        assert await reg.dispatch(None, "hello") is False

    import asyncio
    asyncio.run(_run())


def test_command_registry_name_validation():
    from minidsh.infrastructure.tui.commands import Command, CommandRegistry

    reg = CommandRegistry()
    import pytest as _pt
    with _pt.raises(ValueError):
        reg.register(Command("Bad-Upper", "x", lambda app, arg: None))
    with _pt.raises(ValueError):
        reg.register(Command("9starts-digit", "x", lambda app, arg: None))


def test_command_registry_register_returns_disposer():
    from minidsh.infrastructure.tui.commands import Command, CommandRegistry

    reg = CommandRegistry()
    dispose = reg.register(Command("foo", "x", lambda app, arg: None))
    assert len(reg._commands) == 1
    dispose()
    assert len(reg._commands) == 0


def test_command_registry_duplicate_rejected():
    from minidsh.infrastructure.tui.commands import Command, CommandRegistry

    reg = CommandRegistry()
    reg.register(Command("dup", "x", lambda app, arg: None))
    import pytest as _pt
    with _pt.raises(ValueError):
        reg.register(Command("dup", "y", lambda app, arg: None))


@pytest.mark.asyncio
async def test_unknown_command_falls_through_to_queue():
    """未注册的 /foo 降级为普通用户消息（被 drive 消费进 agent，非命令分发）。"""
    from textual.widgets import Input

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    session = ctx.sessions.create()

    class _Agent:
        def __init__(self):
            self.sent = []

        def send(self, text):
            self.sent.append(text)

        async def run(self):
            pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        inp = app.query_one("#input", Input)
        inp.focus()
        await pilot.press(*"/not-a-real-cmd arg", "enter")
        await pilot.pause()
        # 降级为普通消息 → 被 drive 消费进 agent.send（非命令）
        assert agent.sent == ["/not-a-real-cmd arg"]


# ---------- M6 TUI 审批交互 ----------


@pytest.mark.asyncio
async def test_approval_prompt_renders_and_resolves():
    """TUI 人类应答者：渲染审批提示 + 应答者机制返回 outcome。"""
    import asyncio as _aio
    from minidsh.packages.services.approval import ApprovalProvider, ApprovalRequest

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    ApprovalProvider(ctx)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        req = ApprovalRequest(agent=agent, tool_name="bash", reason="敏感")
        task = _aio.create_task(app._human_approval(req, None))
        await pilot.pause()
        # 审批提示已渲染到状态栏
        label = app.query_one("#status-label")
        assert "审批" in str(label.content)
        # 模拟按键 handler 置位（等价 key_y → _resolve_approval）
        app._resolve_approval("allowed-once")
        await pilot.pause()
        outcome = await task
        assert outcome == "allowed-once"
        assert app._approval_future is None  # 已清理


@pytest.mark.asyncio
async def test_approval_reject_and_cancel_resolution():
    """_resolve_approval 覆盖 rejected / cancelled 两种 outcome。"""
    import asyncio as _aio
    from minidsh.packages.services.approval import ApprovalProvider, ApprovalRequest

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    ApprovalProvider(ctx)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        req = ApprovalRequest(agent=agent, tool_name="bash")
        task = _aio.create_task(app._human_approval(req, None))
        await pilot.pause()
        app._resolve_approval("rejected")
        assert await task == "rejected"

        req2 = ApprovalRequest(agent=agent, tool_name="bash")
        task2 = _aio.create_task(app._human_approval(req2, None))
        await pilot.pause()
        app._resolve_approval("cancelled")
        assert await task2 == "cancelled"


def test_approval_key_handlers_map_to_resolution():
    """key_y/key_n/key_escape 正确映射到 _resolve_approval。"""
    import asyncio as _aio

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

    app = TuiApp(ctx, agent)
    # 未挂载时 key handler 直接调用 _resolve_approval（无待审批 future → 忽略，不抛）
    app.key_y()
    app.key_n()
    app.key_escape()
    assert app._approval_future is None


# ---------- M7 状态栏 token 用量 + session title ----------


@pytest.mark.asyncio
async def test_status_shows_title_when_present():
    """有 session/title 事件 → 状态栏优先显示 title。"""
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
    # 预置标题 + 历史（模拟 resume）
    session.log = [
        SessionEvent(session.id, 0, "session/title", {"title": "写代码"}),
        SessionEvent(session.id, 1, "user-message", {"text": "帮我"}),
    ]

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        assert "写代码" in app.query_one("#status-label").content
        assert session.id not in app.query_one("#status-label").content  # title 优先


@pytest.mark.asyncio
async def test_status_shows_token_usage():
    """状态栏显示 token 用量（有 tokenMeter 时）。"""
    from minidsh.packages.services.token_meter import TokenMeterService

    ctx = Context()
    ctx.provide("sessions", SessionStore(ctx))
    llm = _FakeLlm()
    ctx.provide("llm", llm)
    ctx.provide("config", _FakeConfig([{"id": "demo-a", "url": "u", "reasoning_effort": "medium"}]))
    TokenMeterService(ctx)
    session = ctx.sessions.create()

    class _Agent:
        pass

    agent = _Agent()
    agent.session = session

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        assert "tokens" in app.query_one("#status-label").content


@pytest.mark.asyncio
async def test_status_falls_back_to_session_id():
    """无 title → 状态栏回退 session id；无 tokenMeter → '? tokens'。"""
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

    app = TuiApp(ctx, agent)
    async with app.run_test() as pilot:
        content = app.query_one("#status-label").content
        assert session.id in content
        assert "? tokens" in content