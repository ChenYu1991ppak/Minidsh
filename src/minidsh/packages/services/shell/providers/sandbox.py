"""shell 的沙箱 provider：bash 命令经 ctx.sandbox 真 confining 执行（构造即注册 ctx.shell）。

源码对应：dsh-bash-sandbox（sandbox 的消费方）。

与 ``shell-local``（danger-full-access，raw spawn）平级：二者 provide 同一 ``shell``
服务名，经 profile 的 ``remove: [minidsh.shell-local]`` + ``add minidsh.shell-sandbox``
切换（provider 选择走清单，不走进 provider 内部 if 分支）。

命令以 ``["/bin/bash", "-c", cmd]`` 交给 ``ctx.sandbox.confine``，policy 从
``ctx.config`` 的 sandbox 设置派生（缺省 workspace-write，workspaceRoot = 项目根）。
"""
from __future__ import annotations

import asyncio

from ..definition import ShellRequest, ShellResult, ShellService
from minidsh.cordis import CapabilityProvider
from minidsh.packages.services.sandbox.definition import SandboxExecutionPolicy

__all__ = ["SandboxShellService"]

name = "minidsh.shell-sandbox"
inject = ["sandbox", "root", "config"]


class SandboxShellService(ShellService, CapabilityProvider):
    """bash 执行器（confined）：命令经 ctx.sandbox 约束后执行。"""

    def _init(self, ctx):
        self._workspace_root = str(ctx.root) if ctx.has("root") else "."

    async def execute(self, request: ShellRequest) -> ShellResult:
        policy = SandboxExecutionPolicy(mode="workspace-write", workspace_root=self._workspace_root)
        handle = await self.ctx.sandbox.confine(
            ["/bin/bash", "-c", request.cmd], cwd=self._workspace_root, policy=policy
        )
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
    SandboxShellService(ctx)  # 构造即注册 ctx.shell