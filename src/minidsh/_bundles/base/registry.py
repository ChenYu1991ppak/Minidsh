"""内置 base 插件注册表：17 个内置插件名 → 静态 module。

built-in 插件是 minidsh 自身 wheel 的一部分，不依赖 entry-point 发现（那留给第三方）；
这里用一份 name → module 的静态映射，作为 base 装配的 resolver 基线。
"""
from __future__ import annotations

from . import plugins as _p
from ...capabilities.shell.providers import local as shell_local
from ...capabilities.fs.providers import local as fs_local
from ...capabilities.shell.tools import bash as tool_bash
from ...capabilities.fs.tools import read_file as tool_read

__all__ = ["builtin_registry"]


def builtin_registry() -> dict[str, object]:
    """返回 {插件名 → 静态插件 module}。"""
    return {
        "minidsh.config": _p.config,
        "minidsh.root": _p.root,
        "minidsh.sessions": _p.sessions,
        "minidsh.prompt": _p.prompt,
        "minidsh.tools": _p.tools,
        "minidsh.llm-openai": _p.llm,
        "minidsh.shell-local": shell_local,
        "minidsh.fs-local": fs_local,
        "minidsh.tool-bash": tool_bash,
        "minidsh.tool-read": tool_read,
        "minidsh.skills": _p.skills,
        "minidsh.subagents": _p.subagents,
        "minidsh.agents-md": _p.agents_md,
        "minidsh.loop": _p.loop,
        "minidsh.compaction": _p.compaction,
        "minidsh.trace-render": _p.trace_render,
        "minidsh.persistence": _p.persistence,
    }
