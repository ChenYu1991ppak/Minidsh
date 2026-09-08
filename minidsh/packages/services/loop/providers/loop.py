"""base 插件：loop（AgentLoop）。"""
from __future__ import annotations

from minidsh.packages.services.loop import AgentLoop

name = "minidsh.loop"
inject = ["sessions", "llm", "systemPrompt", "tools"]


def apply(ctx):
    AgentLoop(ctx)  # 构造即注册 ctx.agent_loop
