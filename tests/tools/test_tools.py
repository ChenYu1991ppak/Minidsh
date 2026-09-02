"""T9 验收测试：tools 注册 + 守卫管线 + 内置工具（async 化）。"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import (
    PreToolDecision,
    PostToolDecision,
    ToolDefinition,
    ToolOutput,
    ToolExecution,
    ToolResult,
    ToolRuntime,
)
from minidsh.packages.tools import bash as tool_bash
from minidsh.packages.tools import read_file as tool_read
from tests.helpers.world import plug_execution_world


def _ctx() -> tuple[Context, ToolRuntime]:
    ctx = Context()
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)  # 构造即注册 ctx.tools
    return ctx, tools


def _def(name="echo"):
    async def handler(args):
        return f"got {args}"

    return ToolDefinition(
        name=name,
        description="desc",
        parameters={"type": "object", "properties": {}},
        execute=handler,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    )


# ---------- 定义面 ----------


def test_register_and_get():
    ctx, tools = _ctx()
    tools.register(_def())
    assert tools.get("echo") is not None


def test_register_emits_change_and_dispose():
    ctx, tools = _ctx()
    changes = []
    ctx.on("tools/change", lambda ev: changes.append(ev))
    off = tools.register(_def())
    assert changes[-1] == {"name": "echo", "op": "add"}
    off()
    assert changes[-1] == {"name": "echo", "op": "remove"}
    assert tools.get("echo") is None


# ---------- 展示面 ----------


def test_wire_schemas_projects_whitelist():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    out = tools.wire_schemas()
    assert out["knownNames"] == ["echo"]
    assert set(out["schemas"][0]) == {"name", "description", "parameters"}


def test_present_as_code_hides_from_view():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    tools.present_as("echo", "code")
    assert tools.wire_schemas()["knownNames"] == []


def test_render_schemas_mentions_tool():
    ctx, tools = _ctx()
    plug_execution_world(ctx)
    ctx.plugin(tool_read)
    assert "read_file" in tools.render_schemas()


def test_openai_schemas_wraps_function():
    ctx, tools = _ctx()
    plug_execution_world(ctx)
    ctx.plugin(tool_read)
    out = tools.openai_schemas()
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "read_file"


# ---------- 执行面：守卫管线 ----------


async def test_execute_dispatch_body():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    result = await tools.execute(ToolExecution("c1", "echo", {"a": 1}))
    assert result.content == "got {'a': 1}"
    assert result.is_error is False


async def test_guard_denies():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    tools.guard(lambda ex: "禁止 echo" if ex.name == "echo" else None)
    result = await tools.execute(ToolExecution("c1", "echo", {}))
    assert result.is_error is True
    assert result.content == "禁止 echo"


async def test_pre_execute_can_deny_and_short_circuit():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    called = []

    async def block(ex, next):
        return PreToolDecision.deny("blocked by pre")  # 不调 next() 即短路

    async def before(ex, next):
        called.append("p1")
        return await next()

    tools.on_pre_execute(before)
    tools.on_pre_execute(block)  # 最内层先短路
    result = await tools.execute(ToolExecution("c1", "echo", {}))
    assert result.content == "blocked by pre"
    assert result.is_error is True
    assert called == ["p1"]


async def test_post_execute_blocks_result():
    ctx, tools = _ctx()
    tools.register(_def("echo"))

    async def blocker(ex, result, next):
        return PostToolDecision.block("含 secret")

    tools.on_post_execute(blocker)
    result = await tools.execute(ToolExecution("c1", "echo", {}))
    assert result.is_error is True
    assert result.content == "含 secret"


async def test_unknown_tool_is_error():
    ctx, tools = _ctx()
    result = await tools.execute(ToolExecution("c1", "nope", {}))
    assert result.is_error is True
    assert "unknown tool" in result.content


async def test_code_mode_denied():
    ctx, tools = _ctx()
    tools.register(_def("echo"))
    tools.present_as("echo", "code")
    result = await tools.execute(ToolExecution("c1", "echo", {}))
    assert result.is_error is True
    assert "code" in result.content


async def test_output_schema_validation_error():
    """execute 返回值不符 output.schema → 错误结果。"""
    ctx, tools = _ctx()

    async def bad(args):
        return 42  # 声明 string，返回 int

    tools.register(ToolDefinition(
        name="bad",
        description="d",
        parameters={"type": "object", "properties": {}},
        execute=bad,
        output=ToolOutput(schema={"type": "string"}, render=lambda a, v: v),
    ))
    result = await tools.execute(ToolExecution("c1", "bad", {}))
    assert result.is_error is True
    assert "输出校验失败" in result.content


async def test_output_render_produces_content():
    """content 来自 output.render（而非 str 直包）。"""
    ctx, tools = _ctx()

    async def handler(args):
        return {"n": 5}

    tools.register(ToolDefinition(
        name="count",
        description="d",
        parameters={"type": "object", "properties": {}},
        execute=handler,
        output=ToolOutput(
            schema={"type": "object"},
            render=lambda args, value: f"计数 {value['n']}",
        ),
    ))
    result = await tools.execute(ToolExecution("c1", "count", {}))
    assert result.content == "计数 5"


# ---------- 内置工具 ----------


async def test_read_file(tmp_path):
    ctx, tools = _ctx()
    plug_execution_world(ctx)
    ctx.plugin(tool_read)
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    result = await tools.execute(ToolExecution("c1", "read_file", {"path": str(f)}))
    assert result.content == "hello"


async def test_bash_echo():
    ctx, tools = _ctx()
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo hi"}))
    assert "hi" in result.content


async def test_bash_nonzero_exit_reports_stderr():
    ctx, tools = _ctx()
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo err >&2; exit 2"}))
    assert "[exit 2]" in result.content


# ---------- M7: per-agent 隔离（ScopedLayers） ----------


def test_scoped_register_isolates_per_scope():
    from minidsh.packages.core.scope import createScope, scopeOf

    ctx, tools = _ctx()
    tools.register(_def("global-tool"))     # 全局层

    scope = createScope(ctx)
    tools.scoped_register(scope.ctx, _def("scoped-tool"))

    # scope 视角：全局 + 精确层
    key = scopeOf(scope.ctx)
    assert tools.get("global-tool", scope_key=key) is not None
    assert tools.get("scoped-tool", scope_key=key) is not None
    # 全局视角：看不到 scope 精确工具
    assert tools.get("scoped-tool", scope_key=None) is None
    assert tools.get("global-tool") is not None


def test_scope_dispose_removes_scoped_tool():
    from minidsh.packages.core.scope import createScope, scopeOf

    ctx, tools = _ctx()
    scope = createScope(ctx)
    tools.scoped_register(scope.ctx, _def("temp"))
    key = scopeOf(scope.ctx)
    assert tools.get("temp", scope_key=key) is not None
    scope.dispose()  # effect 绑 scope.ctx 的 fiber → 自动撤回
    assert tools.get("temp", scope_key=key) is None