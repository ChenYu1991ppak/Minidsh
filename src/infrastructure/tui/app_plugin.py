"""minidsh.app-tui-textual：Textual TUI 前端（app 插件）。

经 ``minidsh --profile tui-textual`` 启动交互式终端前端。
``apply(ctx, args)`` 自建 agent（对齐官方「TUI 等待 root agent 就绪」），
装配并启动 Textual 转录视图。

[教学简化] 只做「单会话 TUI」；不实现 resume 前的会话列表 UI（/resume 命令）。
"""
from __future__ import annotations

import sys

name = "minidsh.app-tui-textual"
inject = ["agent_loop", "sessions", "llm", "config", "systemPrompt", "tools"]


def apply(ctx, args) -> int:
    """启动 Textual TUI 前端。"""
    loop = ctx.agent_loop
    session_id = getattr(args, "session", None)
    if session_id:
        agent = _resume_agent(ctx, loop, session_id)
        if agent is None:
            return 1
    else:
        agent = loop.create()
    # 启动 Textual TUI（同旧 _launch_tui_app）
    from .app import TuiApp

    TuiApp(ctx, agent).run()
    return 0


def _resume_agent(ctx, loop, session_id: str):
    """从持久化后端加载会话并恢复 agent（同旧 cli._resume_agent）。"""
    try:
        persistence = ctx.probe("sessionPersistence")
    except Exception:
        persistence = None
    if persistence is None:
        backend = getattr(ctx, "_persistence_backend", None)
        if backend is None:
            print(f"[minidsh] 无持久化后端，无法恢复会话 {session_id!r}", file=sys.stderr)
            return None
        events = backend.load_stored(session_id)
    else:
        events = persistence.load(session_id)
    if not events:
        print(f"[minidsh] 会话 {session_id!r} 不存在或无事件", file=sys.stderr)
        return None
    return loop.resume(session_id, events=events)