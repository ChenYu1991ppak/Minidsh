"""CT6 验收测试：provider 可替换（提供方可替换的核心验证）。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from minidsh.packages.services.shell import ShellService, ShellRequest, ShellResult
from minidsh.packages.services.fs import FsService, FsRequest, FsResult
from minidsh.packages.tools import bash as tool_bash
from minidsh.packages.tools import read_file as tool_read
from tests.helpers.world import plug_execution_world


def _assemble():
    ctx = Context()
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)
    plug_execution_world(ctx)
    ctx.plugin(tool_bash)
    ctx.plugin(tool_read)
    return ctx, tools


class FakeShell(ShellService):
    """替换 provider：回显固定结果，不真正执行命令（非 Service、不注册）。"""

    async def execute(self, request: ShellRequest) -> ShellResult:
        return ShellResult(stdout="fake-输出", stderr="", exit_code=0)


class FakeFs(FsService):
    """替换 provider：返回固定内容，不真正读文件（非 Service、不注册）。"""

    async def execute(self, request: FsRequest) -> FsResult:
        return FsResult(content="fake-内容")


async def test_swap_shell_provider_changes_tool_result():
    """换 provider（重 provide shell）后，consumer 无改动即用新结果。"""
    ctx, tools = _assemble()

    # 替换前：真实 shell 执行
    before = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo real"}))
    assert "real" in before.content

    # 替换：提供假 shell（同名服务覆盖）
    ctx.provide("shell", FakeShell())  # 触发变化即重载 consumer 的注入

    # consumer 依赖 ctx.shell（服务名），变即重载读到 fake（依赖重载时 consumer 会重跑 apply）
    # 注意：provider 互换后，consumer 里 `ctx.shell` 是旧壳的闭包；真正确认覆盖的是 tool 执行读 ctx.tools
    after = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo whatever"}))
    # shell consumer 的 execute 闭包持有旧的 shell；变化即重载后 consumer 重跑 apply 拿到新 shell
    assert after.content == "fake-输出"  # 命令被忽略，假 provider 直接回显


async def test_swap_fs_provider_changes_tool_result(tmp_path):
    ctx, tools = _assemble()

    f = tmp_path / "real.txt"
    f.write_text("real-内容", encoding="utf-8")
    before = await tools.execute(ToolExecution("c1", "read_file", {"path": str(f)}))
    assert before.content == "real-内容"  # 真实读了

    ctx.provide("fs", FakeFs())

    after = await tools.execute(ToolExecution("c1", "read_file", {"path": "/tmp/nonexistent"}))
    assert after.content == "fake-内容"


async def test_consumer_injects_service_not_provider():
    """consumer 依赖服务名 shell/fs，而非 provider 类——换 provider 不需改 consumer。"""
    ctx, tools = _assemble()
    # consumer 已在上面装配；直接重 provide 一个完全不同类的实现
    ctx.provide("shell", FakeShell())

    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "x"}))
    assert result.content == "fake-输出"