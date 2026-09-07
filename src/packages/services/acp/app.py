"""minidsh.app-acp：ACP JSON-RPC stdio server 前端（app 插件）。

经 ``minidsh --profile acp`` 启动，供外部程序（ACP client）调用。
``apply(ctx, args)`` 无需自建 agent——ACP server 按需经 ``session/new`` 创建会话。

[教学简化] 不 spawn 前端子进程（ACP server 本身就是进程）；stdin/stdout 直接走协议。
"""
from __future__ import annotations

name = "minidsh.app-acp"
inject = ["agent_loop", "sessions", "llm", "config", "acp"]


def apply(ctx, args) -> int:
    """启动 ACP JSON-RPC stdio server，阻塞直到客户端断开。"""
    import asyncio

    asyncio.run(ctx.acp.start())
    return 0