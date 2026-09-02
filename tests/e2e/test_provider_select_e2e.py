"""DT3 验收测试：换 provider 只改 profile，不改 consumer/definition/代码。

这是 SPEC-provider-select §8 P4 的核心验收——"提供方可经 profile 选取"的最终证明。
resolver 已统一为 entry-point 发现（内置与第三方同机制），本测试聚焦「后 provide 覆盖」
这个换 provider 的实质：consumer 的 inject 只认服务名 shell，provider 换了它无感。
"""
from __future__ import annotations

import types

from minidsh.cordis import Context
from minidsh.packages.services.shell import ShellService, ShellRequest, ShellResult
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime
from minidsh.packages.services.shell.providers import local as shell_local   # base 默认 provider
from minidsh.packages.tools import bash as tool_bash
from minidsh.infrastructure.bundle import (
    PluginRef,
    merge_plugins,
    apply_removes,
)


class RemoteShellService(ShellService):
    """第三方 remote provider：回显固定结果，不真正执行命令。"""

    async def execute(self, request: ShellRequest) -> ShellResult:
        return ShellResult(stdout="[remote] 结果", stderr="", exit_code=0)


def _remote_provider_module():
    """造一个 module 形态的第三方 provider（entry-point 发现后就是这个形态）。"""
    mod = types.ModuleType("my_shell_remote")
    mod.name = "my-shell-remote"
    mod.inject = []

    def apply(ctx):
        ctx.provide("shell", RemoteShellService())  # 假 provider 非 Service，不注册

    mod.apply = apply
    return mod


# ---------- profile 层：merge/remove ----------


def test_profile_remove_then_add_swaps_provider_in_list():
    """merge + remove 后，激活列表里 shell provider 从 local 换成 remote。"""
    builtin = [
        PluginRef("minidsh.config"),
        PluginRef("minidsh.shell-local"),      # base 默认 provider
        PluginRef("minidsh.tool-bash"),
    ]
    # 覆盖层：移除 local、追加 remote
    user_plugins = [PluginRef("my-shell-remote")]
    user_removes = ["minidsh.shell-local"]

    merged = merge_plugins([builtin, user_plugins])
    final = apply_removes(merged, user_removes)

    names = [r.name for r in final]
    assert "minidsh.shell-local" not in names
    assert "my-shell-remote" in names
    assert "minidsh.tool-bash" in names  # consumer 不动


# ---------- 装配层：换 provider 后端到端生效 ----------


async def test_full_swap_activates_remote_provider():
    """remote provider 后激活（provide shell 覆盖 local）→ consumer 无改动即用新结果。"""
    ctx = Context()
    ctx.provide("config", Config())
    tools = ToolRuntime(ctx)
    ctx.provide("tools", tools)

    # 依序激活：local（provide shell）→ remote（覆盖 provide shell）→ consumer
    ctx.plugin(shell_local)
    ctx.plugin(_remote_provider_module())
    ctx.plugin(tool_bash)

    # 关键断言：ctx.shell 是 remote，consumer（tool-bash，inject=["tools","shell","config"]）
    # 无改动即用新结果
    from minidsh.packages.services.tool_runtime import ToolExecution
    result = await tools.execute(ToolExecution("c1", "bash", {"cmd": "echo whatever"}))
    assert result.content == "[remote] 结果"   # remote 覆盖了 local 的 shell 服务