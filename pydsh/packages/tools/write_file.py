"""write_file 工具的消费方（三角色的「消费方」）：把 fs 写入能力暴露成模型可调的工具。

对齐官方 dsh-tool-fs Write：``inject = ['tools', 'fs']``，注册 ``write_file`` 工具，
execute 调 ``ctx.fs.write_text``。本模块不 import provider（LocalFsService），只依赖
定义 + ctx.fs。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "write_file" 才注册。

↔ packages/fs/tool-fs/src/write.ts
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["WRITE_FILE_PARAMS"]

name = "pydsh.tool-write"
inject = ["tools", "fs", "config"]

WRITE_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "要写入的文件路径（相对项目根或绝对）"},
        "content": {"type": "string", "description": "要写入的文本内容"},
    },
    "required": ["file_path", "content"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "write_file" not in allowed:
        return

    async def execute(args):
        await ctx.fs.write_text(args["file_path"], args["content"])
        return f"Wrote {len(args['content'])} bytes to {args['file_path']}"

    ctx.tools.register(ToolDefinition(
        name="write_file",
        description="写入一个文本文件到磁盘（覆盖已有文件）。",
        parameters=WRITE_FILE_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))