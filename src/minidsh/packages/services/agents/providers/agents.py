"""base 插件：agents（提供 ctx.agents 注册表）。"""
from __future__ import annotations

from minidsh.packages.services.agents import AgentRegistry

name = "minidsh.agents"
inject: list[str] = []


def apply(ctx):
    AgentRegistry(ctx)  # 构造即注册 ctx.agents