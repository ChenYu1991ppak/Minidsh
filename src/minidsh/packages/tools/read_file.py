"""read_file 工具的消费方（三角色的「消费方」）：把 fs 能力暴露成模型可调的工具。

对齐官方能力三层拆分的 consumer：``inject = ['tools', 'fs']``，注册 ``read_file`` 工具，
execute 调 ``ctx.fs``。本模块不 import provider（LocalFsService），只依赖定义 + ctx.fs。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "read_file" 才注册。
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput
from ..services.fs.definition import FsRequest

__all__ = ["READ_FILE_PARAMS"]

name = "minidsh.tool-read"
inject = ["tools", "fs", "config"]

READ_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "要读取的文件路径（相对项目根或绝对）"},
    },
    "required": ["path"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "read_file" not in allowed:
        return

    async def execute(args):
        result = await ctx.fs.execute(FsRequest(path=args["path"]))
        return result.content

    ctx.tools.register(ToolDefinition(
        name="read_file",
        description="读取工作区一个文本文件的内容。",
        parameters=READ_FILE_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))