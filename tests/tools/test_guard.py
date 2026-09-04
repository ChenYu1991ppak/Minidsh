"""M2 验收测试：GuardRegistry + ToolGuard + repeat-tool-reminder。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import (
    ToolDefinition,
    ToolOutput,
    ToolExecution,
    ToolRuntime,
    GuardRegistry,
    RepeatedToolReminder,
    PostToolDecision,
)


def _exec(name="bash", arguments=None, session_id="session-0001"):
    """造一个带 agent.session.id 的 ToolExecution（repeat 链 key 用）。"""
    from itertools import count

    _id = count()

    class _Agent:
        class _Session:
            id = session_id

        session = _Session()

    ex = ToolExecution(call_id=f"call-{next(_id)}", name=name, arguments=arguments or {})
    ex.agent = _Agent()
    return ex


# ---------- GuardRegistry ----------


def test_guard_registry_evaluate_returns_first_denial():
    reg = GuardRegistry()
    reg.register(lambda ex: None)
    reg.register(lambda ex: "blocked" if ex.name == "bash" else None)
    reg.register(lambda ex: "later")  # 不该被命中（前一个已拒绝）
    assert reg.evaluate(_exec("bash")) == "blocked"


def test_guard_registry_dispose_removes_guard():
    reg = GuardRegistry()
    off = reg.register(lambda ex: "deny")
    assert reg.evaluate(_exec()) == "deny"
    off()
    assert reg.evaluate(_exec()) is None


def test_guard_registry_empty_evaluates_none():
    reg = GuardRegistry()
    assert reg.evaluate(_exec()) is None
    assert not reg
    assert len(reg) == 0


# ---------- GuardRegistry 与 ToolRuntime 集成 ----------


def _ctx():
    ctx = Context()
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)

    async def handler(args):
        return "ok"

    tools.register(ToolDefinition(
        name="bash",
        description="d",
        parameters={"type": "object", "properties": {}},
        execute=handler,
        output=ToolOutput(schema={"type": "string"}, render=lambda a, v: v),
    ))
    return ctx, tools


async def test_runtime_guard_via_registry_denies():
    ctx, tools = _ctx()
    tools.guard(lambda ex: "禁止 bash" if ex.name == "bash" else None)
    result = await tools.execute(_exec("bash"))
    assert result.is_error is True
    assert result.content == "禁止 bash"


async def test_runtime_guard_via_registry_allows():
    ctx, tools = _ctx()
    tools.guard(lambda ex: None)
    result = await tools.execute(_exec("bash"))
    assert result.is_error is False
    assert result.content == "ok"


# ---------- repeat-tool-reminder ----------


def test_repeat_reminder_triggers_at_threshold():
    r = RepeatedToolReminder(thresholds=[3])
    ex = _exec("bash", {"cmd": "echo hi"}, session_id="s1")
    assert r.observe(ex) is None  # 1
    assert r.observe(ex) is None  # 2
    out = r.observe(ex)            # 3 → gentle reminder
    assert out is not None
    assert "repeating the exact same tool call" in out


def test_repeat_reminder_detailed_later_threshold():
    r = RepeatedToolReminder(thresholds=[3, 5])
    ex = _exec("bash", {"cmd": "echo hi"}, session_id="s1")
    for _ in range(4):
        r.observe(ex)
    out = r.observe(ex)  # 5 → detailed
    assert "Repeated tool call detected" in out
    assert "consecutive_calls: 5" in out


def test_repeat_reminder_maxes_arguments_preview():
    r = RepeatedToolReminder(thresholds=[2, 3], arguments_preview_chars=10)
    ex = _exec("write", {"content": "x" * 100}, session_id="s1")
    # count=1: no trigger; count=2: gentle (threshold[0]); count=3: detailed (threshold[1])
    r.observe(ex)  # 1
    r.observe(ex)  # 2 → gentle
    out = r.observe(ex)  # 3 → detailed (with preview cap)
    assert "more chars" in out


def test_repeat_reminder_key_sort_canonicalizes():
    r = RepeatedToolReminder(thresholds=[3])
    a = _exec("bash", {"a": 1, "b": 2}, session_id="s1")
    b = _exec("bash", {"b": 2, "a": 1}, session_id="s1")  # key 顺序不同
    # a 两次 (count=2), b 一次应算同链 → count=3 触发
    assert r.observe(a) is None
    assert r.observe(a) is None
    out = r.observe(b)  # 同 key → 连续第 3 次
    assert out is not None


def test_repeat_reminder_reset_breaks_chain():
    r = RepeatedToolReminder(thresholds=[3])
    ex = _exec("bash", {"cmd": "x"}, session_id="s1")
    r.observe(ex)
    r.observe(ex)
    r.reset("s1")
    assert r.observe(ex) is None  # 重置后重新从 1 计


def test_repeat_reminder_different_tool_neither_counts_nor_resets():
    r = RepeatedToolReminder(thresholds=[3])
    a = _exec("bash", {"cmd": "x"}, session_id="s1")
    b = _exec("read_file", {"path": "x"}, session_id="s1")
    r.observe(a)
    r.observe(a)
    r.observe(b)            # 不同工具 → chain 重置为 read_file:1
    assert r.observe(b) is None  # read_file 第 2 次，仍未达阈值
    out = r.observe(b)      # read_file 第 3 次 → 触发
    assert out is not None


def test_repeat_reminder_per_session_isolation():
    r = RepeatedToolReminder(thresholds=[3])
    a = _exec("bash", {"cmd": "x"}, session_id="s1")
    b = _exec("bash", {"cmd": "x"}, session_id="s2")
    r.observe(a)
    r.observe(a)
    # s2 是独立 chain，从 1 计
    assert r.observe(b) is None


async def test_post_execute_additional_contexts_append():
    """post-execute 监听器注入 additional_contexts 后，ToolResult.content 追加提醒。"""
    ctx, tools = _ctx()

    async def enricher(ex, result, next_):
        downstream = await next_()
        return PostToolDecision(
            kind=downstream.kind,
            feedback=downstream.feedback,
            additional_contexts=("reminder text",),
        )

    tools.on_post_execute(enricher)
    result = await tools.execute(_exec("bash"))
    assert "ok" in result.content
    assert "reminder text" in result.content