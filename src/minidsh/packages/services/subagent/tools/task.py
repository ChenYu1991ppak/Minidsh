"""task 委派工具：把任务交给 subagent。

源码对应：packages/subagent/tool-subagent 的委派工具。

消费方视角：loop 借本工具调用 ``ctx.subagents.task``，把一段任务文本 + agent 名
提交给传输 provider 派生出隔离子 agent。派生/结算在**父会话** timeline 上记录
``subagent-spawn`` / ``subagent-result``（父侧可观测），子 agent 自己的事件留在
独立的子会话日志里。

父会话定位：从 ``ctx._session_stack`` 取栈顶（loop 在 run 期间压栈）。
provider 选择：``fork=true`` → ``fork`` 传输（继承父上下文）；否则 ``in-process``。
"""
from __future__ import annotations

from ..definition import SubagentRegistry, SubagentError
from ...tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["make_task_tool"]

TASK_PARAMS = {
    "type": "object",
    "properties": {
        "agent": {"type": "string", "description": "要委派的 agent 名（对应 agents/<name>.md）"},
        "task": {"type": "string", "description": "委派给子 agent 的任务文本"},
        "fork": {"type": "boolean", "description": "是否继承父上下文（fork=true 继承，spawn 从零）"},
        "max_depth": {"type": "integer", "description": "允许的最大委派深度"},
    },
    "required": ["agent", "task"],
}


def make_task_tool(subagents: SubagentRegistry) -> ToolDefinition:
    """构造 task 工具，闭包持有 ``ctx.subagents``。"""

    def _parent_session(ctx):
        stack = getattr(ctx, "_session_stack", None)
        return stack[-1] if stack else None

    async def execute(args: dict) -> str:
        ctx = subagents.ctx
        parent = _parent_session(ctx)
        agent_name = args.get("agent", "")
        task_text = args.get("task", "")
        fork = bool(args.get("fork", False))

        if parent is not None:
            parent.append("subagent-spawn", {"agent": agent_name, "task": task_text, "fork": fork})

        try:
            result = await subagents.task({
                "provider": "fork" if fork else "in-process",
                "agent": agent_name,
                "task": task_text,
                "parent_messages": list(parent.messages) if fork and parent else [],
                "max_depth": args.get("max_depth", 3),
            })
        except SubagentError as exc:
            if parent is not None:
                parent.append("subagent-result", {"agent": agent_name, "result": f"[{exc.code}] {exc}"})
            return f"[{exc.code}] {exc}"

        reply = f"{agent_name} 返回：{result.text}" if result.text else f"{agent_name} 返回（空）"
        if parent is not None:
            parent.append("subagent-result", {"agent": agent_name, "result": result.text})
        return reply

    return ToolDefinition(
        name="task",
        description="委派任务给指定的子 agent。args: agent(名), task(文本), fork(是否继承上下文), max_depth。",
        parameters=TASK_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    )