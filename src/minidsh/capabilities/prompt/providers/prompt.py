"""base 插件：prompt（SystemPromptService）。"""
from __future__ import annotations

from minidsh.capabilities.prompt import SystemPromptService

name = "minidsh.prompt"
inject: list[str] = []


def apply(ctx):
    SystemPromptService(ctx)  # 构造即注册 ctx.systemPrompt
