"""内置 base 插件注册表：17 个内置插件名 → 静态 plugin module。

built-in 插件是 minidsh 自身 wheel 的一部分，不依赖 entry-point 发现（那留给第三方）；
每个插件是 module 形态（name/inject/apply），散落在各自 capability 的 ``providers/``
（+ applications 的 loop/trace/workspace providers + infrastructure 的 config provider）。
这里用一份 name → module 的静态映射，作为 base 装配的 resolver 基线。
"""
from __future__ import annotations

from ...capabilities.session.providers import sessions, persistence
from ...capabilities.prompt.providers import prompt, agents_md
from ...capabilities.tools.providers import tools as tools_plugin
from ...capabilities.skills.providers import skills
from ...capabilities.subagent.providers import subagents
from ...capabilities.compaction.providers import compaction
from ...capabilities.llm.providers import openai as llm_openai
from ...capabilities.shell.providers import local as shell_local
from ...capabilities.fs.providers import local as fs_local
from ...capabilities.shell.tools import bash as tool_bash
from ...capabilities.fs.tools import read_file as tool_read
from ...applications.loop.providers import loop
from ...applications.trace.providers import trace_render
from ...applications.workspace.providers import root
from ...infrastructure.config.providers import config

__all__ = ["builtin_registry"]


def builtin_registry() -> dict[str, object]:
    """返回 {插件名 → 静态插件 module}。"""
    return {
        "minidsh.config": config,
        "minidsh.root": root,
        "minidsh.sessions": sessions,
        "minidsh.prompt": prompt,
        "minidsh.tools": tools_plugin,
        "minidsh.llm-openai": llm_openai,
        "minidsh.shell-local": shell_local,
        "minidsh.fs-local": fs_local,
        "minidsh.tool-bash": tool_bash,
        "minidsh.tool-read": tool_read,
        "minidsh.skills": skills,
        "minidsh.subagents": subagents,
        "minidsh.agents-md": agents_md,
        "minidsh.loop": loop,
        "minidsh.compaction": compaction,
        "minidsh.trace-render": trace_render,
        "minidsh.persistence": persistence,
    }