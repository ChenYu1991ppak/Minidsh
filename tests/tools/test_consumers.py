"""CT4 验收测试：tool-bash / tool-read consumer（经 provider 服务）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from minidsh.packages.tools import bash as tool_bash
from minidsh.packages.tools import read_file as tool_read
from tests.helpers.world import plug_execution_world


def _assemble(allowed=None, with_bash=True, with_read=True):
    """装配：config + tools(空运行时) + 执行世界(subprocess→shell→fs) + 需要的 consumer。"""
    ctx = Context()
    ctx.provide("config", Config(allowed_tools=allowed))
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    if with_bash:
        ctx.plugin(tool_bash)
    if with_read:
        ctx.plugin(tool_read)
    return ctx, tools


async def test_bash_consumer_registers_and_executes():
    ctx, tools = _assemble()
    assert tools.get("bash") is not None
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo hi"}))
    assert result.is_error is False
    assert "hi" in result.content


async def test_read_consumer_registers_and_executes(tmp_path):
    ctx, tools = _assemble()
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    result = await tools.execute(ToolExecution("c1", "read_file", {"path": str(f)}))
    assert result.content == "hello"


async def test_read_consumer_nonzero_stderr():
    ctx, tools = _assemble()
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo err >&2; exit 2"}))
    assert "[exit 2]" in result.content


async def test_whitelist_filters_bash():
    """白名单不含 bash → consumer 不注册 bash；但 read_file 仍注册。"""
    ctx, tools = _assemble(allowed=["read_file"])
    assert tools.get("bash") is None
    assert tools.get("read_file") is not None


async def test_whitelist_none_registers_all():
    ctx, tools = _assemble(allowed=None)
    assert tools.get("bash") is not None
    assert tools.get("read_file") is not None