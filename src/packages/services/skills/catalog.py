"""skill-catalog 工具：向模型暴露「列举 / 加载」技能的能力。

源码对应：packages/skill/tool-skill 的 catalog 工具（tool-skill/src/index.ts）。

通过普通 ToolDefinition 接入 tools 管线（与 bash 同构）。两个动作：
- ``action=list``：返回目录（技能名 + 描述）
- ``action=load``：加载指定技能正文并注入 system-prompt（惰性，spec §6.2）

加载成功会走 ``SkillRegistry.load``，后者广播 cordis 事件 ``skills/load``；
loop 订阅该事件，产会话事件 ``skill-loaded``（跨层桥接职责在 loop，见 T9/T10 分层）。
"""
from __future__ import annotations

from .definition import SkillRegistry
from ..tool_runtime.runtime import ToolDefinition, ToolOutput

__all__ = ["make_catalog_tool"]

CATALOG_PARAMS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "load"],
            "description": "list=列出可用技能，load=加载指定技能正文并注入提示词",
        },
        "name": {"type": "string", "description": "action=load 时要加载的技能名"},
    },
    "required": ["action"],
}


def make_catalog_tool(skills: SkillRegistry) -> ToolDefinition:
    """构造目录工具，闭包持有 ``ctx.skills``。"""

    async def execute(args: dict) -> str:
        action = args.get("action")
        if action == "list":
            summaries = skills.list()
            if not summaries:
                return "（无可用技能）"
            return "\n".join(f"- {s.name}: {s.description}" for s in summaries)
        if action == "load":
            name = args.get("name")
            if not name:
                return "[error] action=load 需要提供 name"
            definition = skills.load(name)
            if definition is None:
                return f"[error] 未找到技能：{name}"
            return f"已加载技能 {name}：{definition.description}"
        return f"[error] 未知 action：{action}"

    return ToolDefinition(
        name="skill-catalog",
        description="列出或加载技能。action=list 列出全部；action=load name=<n> 加载技能正文。",
        parameters=CATALOG_PARAMS,
        execute=execute,
        output=ToolOutput(schema={"type": "string"}, render=lambda args, value: value),
    )