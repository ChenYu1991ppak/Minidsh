"""todo_write 工具的消费方：管理任务列表，暴露成模型可调的工具。

每次调用替换整个任务列表，产 ``todo-update`` 会话事件（审计面，不进模型 transcript）。
[教学简化] 无 item id、无 session projection；官方有专用的 todo projection 做
last-write-wins 折叠。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，
None 或含 "todo_write" 才注册。

↔ packages/todo/tool-todo/src/index.ts
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["TODO_WRITE_PARAMS"]

name = "pydsh.tool-todo"
inject = ["tools", "config"]

TODO_WRITE_PARAMS = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "description": "完整的任务列表（替换整个列表）",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "任务描述"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "description": "任务状态",
                    },
                    "activeForm": {
                        "type": "string",
                        "description": "进行中时显示的动词短语（如 'Writing tests'）",
                    },
                },
                "required": ["content", "status"],
            },
        },
    },
    "required": ["todos"],
}


def _parent_session(ctx):
    """获取当前运行的 agent 的 session（与 task.py 同模式）。"""
    stack = getattr(ctx, "_session_stack", None)
    return stack[-1] if stack else None


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "todo_write" not in allowed:
        return

    async def execute(args):
        todos = args["todos"]
        session = _parent_session(ctx)
        if session is not None:
            session.append("todo-update", {"todos": todos})

        # 格式化为可读的文本列表
        lines = []
        for i, t in enumerate(todos):
            status_mark = {"pending": " ", "in_progress": ">", "completed": "x"}[t["status"]]
            active = t.get("activeForm", t["content"])
            display = active if t["status"] == "in_progress" else t["content"]
            lines.append(f"[{status_mark}] {display}")
        return "\n".join(lines)

    ctx.tools.register(ToolDefinition(
        name="todo_write",
        description=(
            "创建和更新任务列表。todos 是一个任务数组，每个任务有 content（内容）"
            "和 status（pending/in_progress/completed）。"
            "每次调用替换整个列表。"
        ),
        parameters=TODO_WRITE_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))