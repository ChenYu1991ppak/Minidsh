"""bash 工具的消费方（三角色的「消费方」）：把 shell 能力暴露成模型可调的工具。

对齐官方 dsh-tool-bash：``inject = ['tools', 'shell']``，注册 ``bash`` 工具，execute
调 ``ctx.shell``。本模块不 import provider（LocalShellService），只依赖定义 + ctx.shell。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "bash" 才注册。
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput
from ..services.shell.definition import ShellRequest

__all__ = ["BASH_PARAMS"]

name = "minidsh.tool-bash"
inject = ["tools", "shell", "config"]

BASH_PARAMS = {
    "type": "object",
    "properties": {
        "cmd": {"type": "string", "description": "要执行的 shell 命令"},
    },
    "required": ["cmd"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "bash" not in allowed:
        return

    async def execute(args):
        result = await ctx.shell.execute(ShellRequest(cmd=args["cmd"]))
        if result.exit_code != 0:
            return f"[exit {result.exit_code}]\n{result.stderr.strip()}"
        return (result.stdout + result.stderr).strip()

    ctx.tools.register(ToolDefinition(
        name="bash",
        description="在工作区执行一条 shell 命令，返回 stdout/stderr（教学版，无沙箱）。",
        parameters=BASH_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))