"""glob 工具的消费方：按 glob 模式查找文件，暴露成模型可调的工具。

消费 ctx.shell 执行 find 命令（与 bash.py 同模式）。
[教学简化] 官方用 ripgrep --files 二进制；教学版用 find。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "glob" 才注册。

↔ packages/fs/tool-fs-search/src/glob.ts
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput
from ..services.shell.definition import ShellRequest

__all__ = ["GLOB_PARAMS"]

name = "minidsh.tool-glob"
inject = ["tools", "shell", "config"]

GLOB_PARAMS = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "glob 模式，如 '**/*.py' 或 '*.md'"},
        "path": {"type": "string", "description": "搜索起始路径，默认为当前目录"},
    },
    "required": ["pattern"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "glob" not in allowed:
        return

    async def execute(args):
        pattern = args["pattern"]
        path = args.get("path", ".")
        # 用 find 做 glob 匹配（支持 ** 递归），上限 100 条
        cmd = f"find {path} -path '*/{pattern}' -type f 2>/dev/null | head -100"
        result = await ctx.shell.execute(ShellRequest(cmd=cmd))
        if result.exit_code != 0 and result.stderr.strip():
            return f"[exit {result.exit_code}]\n{result.stderr.strip()}"
        output = (result.stdout + result.stderr).strip()
        return output if output else "No files found."

    ctx.tools.register(ToolDefinition(
        name="glob",
        description="按 glob 模式查找文件。返回匹配的文件路径列表（最多 100 条）。",
        parameters=GLOB_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))