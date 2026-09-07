"""shell 的本地 provider：消费 subprocess 执行 bash 命令（构造即注册 ctx.shell）。

源码对应：dsh-bash-local（shell 是 subprocess 的 consumer，用 collect 批量输出）。

三角色的「提供方」：实现 ShellService，把一条 bash 命令包装成
``["/bin/bash", "-c", cmd]`` 交给 ``ctx.subprocess``（argv 绝不 shell 解释），再从
collected 输出填回 ShellResult。

[教学简化] 相对官方：
- cwd 用父进程 cwd（``os.getcwd()``），贴现无 workspace 入参（官方来自调用会话不可变 cwd）；
- deadline 由本 consumer 自己持有：``asyncio.wait_for`` 超时即 ``handle.terminate()``
  （官方「caller owns deadlines」，subprocess seam 只反应 abort）。
"""
from __future__ import annotations

import asyncio
import os

from ..definition import ShellRequest, ShellResult, ShellService
from minidsh.cordis import CapabilityProvider
from minidsh.packages.services.subprocess.definition import SubprocessSpawnSpec, SubprocessStdio

__all__ = ["LocalShellService"]

name = "minidsh.shell-local"
inject = ["subprocess"]


class LocalShellService(ShellService, CapabilityProvider):
    """本地 bash 执行器：命令经 ctx.subprocess 跑，collect 批量输出。"""

    async def execute(self, request: ShellRequest) -> ShellResult:
        spec = SubprocessSpawnSpec(
            argv=["/bin/bash", "-c", request.cmd],
            cwd=os.getcwd(),
            stdio=SubprocessStdio(stdout="collect", stderr="collect"),
        )
        handle = await self.ctx.subprocess.spawn(spec)
        try:
            outcome = await asyncio.wait_for(handle.done, timeout=request.timeout_seconds)
        except asyncio.TimeoutError:
            handle.terminate()
            return ShellResult(stdout="", stderr="command timed out", exit_code=-1)

        collected = handle.collected
        stdout = collected.get("stdout")
        stderr = collected.get("stderr")
        return ShellResult(
            stdout=stdout.text if stdout else "",
            stderr=stderr.text if stderr else "",
            exit_code=outcome.exit_code or 0,
        )


def apply(ctx):
    LocalShellService(ctx)  # 构造即注册 ctx.shell