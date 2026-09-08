"""ask_user_question 工具的消费方：向用户提问，暴露成模型可调的工具。

产 ``user-question`` 会话事件（审计面，不进模型 transcript），TUI/ACP 渲染为交互式
选择卡片。模型调用此工具后应停止生成，等待用户回答。

[教学简化] 无真正的 pause/resume 机制——依赖 LLM 训练行为（调用后停止）；
agent_loop 侧有兜底：执行 ask_user_question 后立即 break react 循环。

白名单：经 ``inject=["config"]`` 读 ``ctx.config.allowed_tools``，
None 或含 "ask_user_question" 才注册。

↔ packages/interaction/tool-ask-user/src/index.ts
"""
from __future__ import annotations

from ..services.tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["ASK_USER_QUESTION_PARAMS"]

name = "minidsh.tool-ask-user"
inject = ["tools", "config"]

ASK_USER_QUESTION_PARAMS = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "要问用户的问题列表",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "要问用户的问题"},
                    "header": {"type": "string", "description": "问题的简短标题（最多 12 字符）"},
                    "options": {
                        "type": "array",
                        "description": "可选项列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "选项标签"},
                                "description": {
                                    "type": "string",
                                    "description": "选项说明",
                                },
                            },
                            "required": ["label", "description"],
                        },
                    },
                    "multiSelect": {
                        "type": "boolean",
                        "description": "是否允许多选（默认 false）",
                    },
                },
                "required": ["question", "header", "options"],
            },
        },
    },
    "required": ["questions"],
}


def _parent_session(ctx):
    """获取当前运行的 agent 的 session（与 task.py 同模式）。"""
    stack = getattr(ctx, "_session_stack", None)
    return stack[-1] if stack else None


def apply(ctx):
    allowed = ctx.config.allowed_tools
    if allowed is not None and "ask_user_question" not in allowed:
        return

    async def execute(args):
        questions = args["questions"]
        session = _parent_session(ctx)
        if session is not None:
            session.append("user-question", {"questions": questions})

        # 格式化为 LLM 可见的文本（模型看到后应停止生成）
        lines = ["The following questions need user input:"]
        for i, q in enumerate(questions):
            lines.append(f"\nQ{i + 1}: {q['question']}")
            for j, opt in enumerate(q["options"]):
                lines.append(f"  [{j + 1}] {opt['label']}: {opt['description']}")
            if q.get("multiSelect"):
                lines.append("  (multiple selections allowed)")
        lines.append("\nPlease wait for the user to respond before continuing.")
        return "\n".join(lines)

    ctx.tools.register(ToolDefinition(
        name="ask_user_question",
        description=(
            "向用户提问。当遇到歧义或需要用户决策时使用。"
            "问题会渲染为交互式选择卡片。调用此工具后应等待用户回答。"
        ),
        parameters=ASK_USER_QUESTION_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    ))