"""minidsh 内置 base 静态插件包。

每个插件是 module 形态（模块级 name/inject/apply）。依赖经 inject 声明、配置经
ctx.config / ctx.root 读，不闭包捕获 runtime 变量。这组静态插件经 entry-point 组
``minidsh.plugins`` 随包发现，与第三方插件同机制。
"""
from __future__ import annotations

from . import (
    sessions,
    prompt,
    tools,
    loop,
    trace_render,
    skills,
    subagents,
    agents_md,
    compaction,
    persistence,
    config,
    root,
    llm,
)

__all__ = [
    "sessions",
    "prompt",
    "tools",
    "loop",
    "trace_render",
    "skills",
    "subagents",
    "agents_md",
    "compaction",
    "persistence",
    "config",
    "root",
    "llm",
]