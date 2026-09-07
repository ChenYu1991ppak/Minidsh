"""lsp 工具的消费方（三角色的「消费方」）：把 lsp 能力暴露成模型可调的工具。

对齐官方 dsh-tool-lsp：``inject = ['tools', 'lsp']``，注册 ``lsp`` 工具，execute 调
``ctx.lsp.query``。本模块不 import provider，只依赖定义 + ctx.lsp。

模型面用 1-based 坐标（line/character），seam 用零基；本工具做 1-based → 零基转换。
无 provider 处理该扩展名时（``LSP_UNAVAILABLE``）降级 ``available=False``（不抛错）。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``。

[教学简化] 不注册 system-prompt section；不实现官方 tool-lsp 的 render 卡片/会话 cwd 归一。
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput
from ..services.lsp.definition import (
    LspQueryRequest,
    LspPosition,
    LspError,
    LSP_OPERATIONS,
)

__all__ = ["LSP_PARAMS"]

name = "minidsh.tool-lsp"
inject = ["tools", "lsp", "config"]

LSP_PARAMS = {
    "type": "object",
    "properties": {
        "filePath": {"type": "string", "description": "要查询的源文件路径"},
        "operation": {
            "type": "string",
            "description": "语义操作：" + " / ".join(LSP_OPERATIONS),
        },
        "line": {"type": "integer", "description": "1-based 行号"},
        "character": {"type": "integer", "description": "1-based 列号"},
    },
    "required": ["filePath", "operation", "line", "character"],
}

LSP_OUTPUT = {
    "type": "object",
    "properties": {
        "available": {"type": "boolean"},
        "kind": {"type": "string"},
        "locations": {"type": "array"},
        "hover": {},
    },
    "required": ["available"],
}


def _parse_args(args: dict):
    """校验参数并做 1-based → 零基转换；返回 LspQueryRequest。"""
    file_path = (args.get("filePath") or "").strip()
    if not file_path:
        raise ValueError("filePath must be a non-empty string")
    operation = args.get("operation")
    if operation not in LSP_OPERATIONS:
        raise ValueError(f"operation must be one of {LSP_OPERATIONS}, got {operation!r}")
    line = args.get("line")
    character = args.get("character")
    if not isinstance(line, int) or line < 1:
        raise ValueError("line must be a 1-based positive integer")
    if not isinstance(character, int) or character < 1:
        raise ValueError("character must be a 1-based positive integer")
    return LspQueryRequest(
        operation=operation,
        filePath=file_path,
        position=LspPosition(line=line - 1, character=character - 1),
    )


def _result_to_value(result) -> dict:
    """把 LspQueryResult 转成可 JSON 序列化的规范值。"""
    if result.kind == "hover":
        hover = result.hover
        return {
            "available": True,
            "kind": "hover",
            "hover": ({"contents": hover.contents} if hover is not None else None),
        }
    locations = []
    for loc in result.locations:
        entry = {"uri": loc.uri}
        if loc.range is not None:
            entry["range"] = {
                "start": {"line": loc.range.start.line, "character": loc.range.start.character},
                "end": {"line": loc.range.end.line, "character": loc.range.end.character},
            }
        locations.append(entry)
    return {"available": True, "kind": "locations", "locations": locations}


def _render(args, value: dict) -> str:
    if not value.get("available"):
        return f"lsp unavailable: {value.get('error', 'no provider handles this file')}"
    if value["kind"] == "hover":
        hover = value.get("hover")
        return hover["contents"] if hover else "No hover information."
    locations = value.get("locations") or []
    if not locations:
        return "No locations found."
    lines = []
    for loc in locations:
        r = loc.get("range")
        pos = f":{r['start']['line'] + 1}:{r['start']['character'] + 1}" if r else ""
        lines.append(f"- {loc['uri']}{pos}")
    return "\n".join(lines)


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "lsp" not in allowed:
        return

    async def execute(args):
        request = _parse_args(args)
        try:
            result = await ctx.lsp.query(request)
            return _result_to_value(result)
        except LspError as exc:
            return {"available": False, "error": str(exc), "code": exc.code}

    ctx.tools.register(ToolDefinition(
        name="lsp",
        description="代码语义查询：goToDefinition / findReferences / goToImplementation / hover。",
        parameters=LSP_PARAMS,
        execute=execute,
        output=ToolOutput(schema=LSP_OUTPUT, render=_render),
    ))