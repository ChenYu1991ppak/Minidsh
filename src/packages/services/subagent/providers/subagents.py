"""base 插件：subagents（SubagentRegistry + in-process providers + task 工具）。"""
from __future__ import annotations

from minidsh.packages.services.subagent import SubagentRegistry, InProcessSubagentProvider, make_task_tool
from ._helpers import _load_agents

name = "minidsh.subagents"
inject = ["tools", "root"]


def apply(ctx):
    tools = ctx.tools
    subagents = SubagentRegistry(ctx)
    subagents.register_provider(InProcessSubagentProvider("in-process", inherits_parent_context=False))
    subagents.register_provider(InProcessSubagentProvider("fork", inherits_parent_context=True))
    _load_agents(ctx.root, subagents)
    tools.register(make_task_tool(subagents))
