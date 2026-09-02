"""测试装配辅助：执行世界（subprocess → shell → fs）。

M8 后 shell-local 依赖 ctx.subprocess（消费 seam），装配时必须先 subprocess 后 shell。
本辅助把这三层「执行世界」一次插好，bash/read 工具随后 plugin 即可。
"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.subprocess.providers import local as subprocess_local
from minidsh.packages.services.shell.providers import local as shell_local
from minidsh.packages.services.fs.providers import local as fs_local

__all__ = ["plug_execution_world"]


def plug_execution_world(ctx: Context) -> Context:
    """装配 subprocess → shell-local → fs-local；返回 ctx。"""
    ctx.plugin(subprocess_local)
    ctx.plugin(shell_local)
    ctx.plugin(fs_local)
    return ctx