"""edit_file 工具的消费方（三角色的「消费方」）：把 fs 编辑能力暴露成模型可调的工具。

对齐官方 dsh-tool-fs Edit：``inject = ['tools', 'fs']``，注册 ``edit_file`` 工具，
execute 调 ``ctx.fs.edit_text``。本模块不 import provider（LocalFsService），只依赖
定义 + ctx.fs。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，None 或含 "edit_file" 才注册。

↔ packages/fs/tool-fs/src/edit.ts
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["EDIT_FILE_PARAMS"]

name = "pydsh.tool-edit"
inject = ["tools", "fs", "config"]

EDIT_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "file_path": {"type": "string", "description": "要编辑的文件路径（相对项目根或绝对）"},
        "old_string": {"type": "string", "description": "要替换的原始字符串（必须唯一匹配）"},
        "new_string": {"type": "string", "description": "替换后的新字符串"},
        "replace_all": {
            "type": "boolean",
            "description": "是否替换所有匹配项（默认 false，仅替换第一个匹配）",
        },
    },
    "required": ["file_path", "old_string", "new_string"],
}


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "edit_file" not in allowed:
        return

    async def execute(args):
        await ctx.fs.edit_text(
            args["file_path"],
            args["old_string"],
            args["new_string"],
            args.get("replace_all", False),
        )
        return f"Edited {args['file_path']}"

    ctx.tools.register(ToolDefinition(
        name="edit_file",
        description=(
            "基于字符串替换编辑文件。old_string 必须唯一匹配文件中的内容"
            "（除非 replace_all=true）。"
        ),
        parameters=EDIT_FILE_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))