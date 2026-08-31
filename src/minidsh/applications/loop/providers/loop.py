"""base 插件：loop（AgentLoop）。"""
from __future__ import annotations

from minidsh.applications.loop import AgentLoop

name = "minidsh.loop"
inject = ["sessions", "llm", "systemPrompt", "tools"]


def apply(ctx):
    ctx.provide("agent_loop", AgentLoop(ctx))
