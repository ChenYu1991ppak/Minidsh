"""grep 工具的消费方：在文件中搜索匹配的文本模式，暴露成模型可调的工具。

消费 ctx.shell 执行 grep -rn 命令（与 bash.py 同模式）。
[教学简化] 官方用 ripgrep --json 二进制；教学版用 GNU grep。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "grep" 才注册。

↔ packages/fs/tool-fs-search/src/grep.ts
"""
from __future__ import annotations

import shlex

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput
from ..services.shell.definition import ShellRequest

__all__ = ["GREP_PARAMS"]

name = "minidsh.tool-grep"
inject = ["tools", "shell", "config"]

GREP_PARAMS = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "要搜索的文本模式（正则表达式）"},
        "path": {"type": "string", "description": "搜索起始路径，默认为当前目录"},
        "include": {"type": "string", "description": "文件名匹配模式，如 '*.py'（可选）"},
    },
    "required": ["pattern"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "grep" not in allowed:
        return

    async def execute(args):
        pattern = args["pattern"]
        path = args.get("path", ".")
        include = args.get("include")
        include_flag = f'--include="{include}"' if include else ""
        # 上限 50 条匹配
        cmd = f"grep -rn {include_flag} {shlex.quote(pattern)} {path} 2>/dev/null | head -50"
        result = await ctx.shell.execute(ShellRequest(cmd=cmd))
        # grep exit 1 = no matches (not an error)
        if result.exit_code == 1 and not result.stdout.strip():
            return "No matches found."
        if result.exit_code > 1:
            return f"[exit {result.exit_code}]\n{result.stderr.strip()}"
        output = (result.stdout + result.stderr).strip()
        return output if output else "No matches found."

    ctx.tools.register(ToolDefinition(
        name="grep",
        description=(
            "在文件中搜索匹配的文本模式（正则表达式）。"
            "返回匹配行及文件名和行号（最多 50 条）。"
        ),
        parameters=GREP_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))