"""shell 的本地 provider（三角色的「提供方」）：subprocess 执行命令。

对齐官方 dsh-bash-local：实现 ShellService，经 module 插件 provide 到 ctx.shell。
provider 只 provide 服务；把「执行」暴露成工具是 consumer（tool-bash）的职责。
"""
from __future__ import annotations

import subprocess

from ..definition import ShellRequest, ShellResult, ShellService
from ....cordis import CapabilityProvider

__all__ = ["LocalShellService"]

name = "minidsh.shell-local"
inject = []


class LocalShellService(ShellService, CapabilityProvider):
    """在本地用 subprocess 执行命令。[教学简化] 无沙箱，安全边界交 guard 层。"""

    async def execute(self, request: ShellRequest) -> ShellResult:
        proc = subprocess.run(
            request.cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
        )
        return ShellResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )


def apply(ctx):
    LocalShellService(ctx)  # 构造即注册 ctx.shell