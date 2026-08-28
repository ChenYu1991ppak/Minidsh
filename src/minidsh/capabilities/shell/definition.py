"""shell 能力定义：执行一条 shell 命令的能力（三角色的「定义」）。

对齐官方 dsh-shell（packages/shell/dsh-shell）：定义 Service + 请求/结果类型。
Provider（如 local / 远程 / 沙箱）与 Consumer（tool-bash）都只依赖本定义。

与 llm/seam.py 同构：本模块只声明「做什么」，不含实现细节。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...cordis import Service

__all__ = ["ShellRequest", "ShellResult", "ShellService"]


@dataclass(frozen=True)
class ShellRequest:
    """一条命令执行请求。"""

    cmd: str
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ShellResult:
    """命令执行结果（退出码 + stdout/stderr）。"""

    stdout: str
    stderr: str
    exit_code: int


class ShellService(Service):
    """ctx.shell：执行命令的能力定义。多个 provider 可替换实现。"""

    async def execute(self, request: ShellRequest) -> ShellResult:
        raise NotImplementedError