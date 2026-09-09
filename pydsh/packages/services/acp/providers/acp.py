"""base 插件：acp（提供 ctx.acp ACP JSON-RPC server）。"""
from __future__ import annotations

from pydsh.packages.services.acp import AcpServerProvider

name = "pydsh.acp"
inject = ["agent_loop", "sessions", "llm", "config"]


def apply(ctx):
    AcpServerProvider(ctx)  # 构造即注册 ctx.acp