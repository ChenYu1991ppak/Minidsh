"""内置 base 插件工厂表与 base 清单。

16 个具名插件（对应 SPEC-manifest §2.4 + shell/fs 三拆），split 自原 loader 的硬编码装配。
每个插件经 ``factory(root, cfg, ...)`` 生成 module 形态的插件（name/inject/apply）。

依赖方向（inject 声明，非书写顺序）：
    config / sessions / llm / prompt / tools（无依赖）
    shell / fs（provider）；tool-bash / tool-read（inject tools+shell/fs+config）
    skills+subagents（inject tools）；agents-md（inject systemPrompt）
    loop（inject sessions/llm/systemPrompt/tools）
    compaction（inject sessions/llm）；trace-render / persistence（inject sessions）
"""
from __future__ import annotations

import types
from pathlib import Path
from typing import Any, Callable

from ...infrastructure.config import Config
from ...capabilities.session import SessionStore
from ...capabilities.session.persistence import PersistenceCoordinator
from ...capabilities.session.providers.jsonl import JsonlSessionPersistence
from ...capabilities.session.providers.sqlite import SqliteSessionPersistence
from ...capabilities.llm.providers.openai import OpenAILlm
from ...capabilities.prompt import SystemPromptService
from ...capabilities.tools import ToolRuntime
from ...capabilities.shell.providers import local as shell_provider
from ...capabilities.fs.providers import local as fs_provider
from ...capabilities.shell.tools import bash as tool_bash
from ...capabilities.fs.tools import read_file as tool_read
from ...capabilities.skills import FilesystemSkillProvider, SkillRegistry, make_catalog_tool
from ...capabilities.subagent import SubagentRegistry, InProcessSubagentProvider, make_task_tool
from ...applications.loop import AgentLoop
from ...capabilities.compaction import CompactionEngine
from ...applications.trace import ConsoleRenderer

__all__ = ["build_base_plugins", "base_manifest"]


def _module(name: str, inject: list[str], apply: Callable[[Any], None]) -> types.ModuleType:
    """造一个 module 形态插件（module 级 name/inject/apply）。"""
    mod = types.ModuleType(f"minidsh._bundles.base.{name}")
    mod.name = name
    mod.inject = inject
    mod.apply = apply
    return mod


def _build_llm(cfg: Config, llm_client: Any):
    model = cfg.current
    if model is None:
        raise RuntimeError(
            "未配置可用模型：请在 models.json 的 models[] 里至少提供一个模型，"
            "并用 currentModel 或 availableModels 指定当前模型"
        )
    if not model.url:
        raise RuntimeError(
            f"模型 {model.id!r} 未配置 url（OpenAI 兼容 base_url）：该模型不可用。"
            "请在 models.json 里为该模型填写 url 字段。"
        )
    return OpenAILlm(model=model.id, api_key=model.api_key or None, base_url=model.url, client=llm_client)


def _parse_agent_md(text: str) -> tuple[str, str, str] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    frontmatter = text[3:end].strip()
    content = text[end + 4:].strip() if end + 4 < len(text) else ""
    fields = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    if fields.get("name"):
        return fields["name"], fields.get("description", ""), content
    return None


def _load_agents(root: Path, subagents: SubagentRegistry):
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    for path in sorted(agents_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed = _parse_agent_md(text)
        if parsed is not None:
            name, description, content = parsed
        else:
            name, description, content = path.stem, "", text
        subagents.define_agent(name, {"name": name, "description": description, "content": content})


def build_base_plugins(root: Path, cfg: Config, llm_client: Any, quiet: bool) -> dict[str, object]:
    """按配置生成全部内置 base 插件（name → module 形态插件）。"""
    return {
        "minidsh.config": _module("minidsh.config", [], lambda ctx: ctx.provide("config", cfg)),
        "minidsh.sessions": _module("minidsh.sessions", [], lambda ctx: ctx.provide("sessions", SessionStore(ctx))),
        "minidsh.llm": _module("minidsh.llm", [], lambda ctx: ctx.provide("llm", _build_llm(cfg, llm_client))),
        "minidsh.prompt": _module("minidsh.prompt", [], lambda ctx: ctx.provide("systemPrompt", SystemPromptService(ctx))),

        "minidsh.tools": _module("minidsh.tools", [], lambda ctx: _apply_tools(ctx, cfg)),
        "minidsh.shell": shell_provider,
        "minidsh.fs": fs_provider,
        "minidsh.tool-bash": tool_bash,
        "minidsh.tool-read": tool_read,
        "minidsh.skills": _module("minidsh.skills", ["tools"], lambda ctx: _apply_skills(ctx, root)),
        "minidsh.subagents": _module("minidsh.subagents", ["tools"], lambda ctx: _apply_subagents(ctx, root)),
        "minidsh.agents-md": _module("minidsh.agents-md", ["systemPrompt"], lambda ctx: _apply_agents_md(ctx, root)),

        "minidsh.loop": _module("minidsh.loop", ["sessions", "llm", "systemPrompt", "tools"],
                                lambda ctx: ctx.provide("agent_loop", AgentLoop(ctx))),
        "minidsh.compaction": _module("minidsh.compaction", ["sessions", "llm"],
                                      lambda ctx: ctx.provide("compaction", CompactionEngine(
                                          ctx, context_window=cfg.context_window,
                                          threshold_ratio=cfg.compaction_threshold_ratio))),
        "minidsh.trace-render": _module("minidsh.trace-render", ["sessions"],
                                        lambda ctx: setattr(ctx, "_renderer", ConsoleRenderer(ctx))),
        "minidsh.persistence": _module("minidsh.persistence", ["sessions"],
                                       lambda ctx: _apply_persistence(ctx, root, cfg.storage)),
    }


def _apply_tools(ctx, cfg: Config):
    # minidsh.tools 现在只提供空 ToolRuntime；bash/read_file 由 consumer 插件注册。
    ToolRuntime(ctx)


def _apply_skills(ctx, root: Path):
    tools = ctx.tools
    skills = SkillRegistry(ctx)
    skills.register_provider(FilesystemSkillProvider(root))
    tools.register(make_catalog_tool(skills))


def _apply_subagents(ctx, root: Path):
    tools = ctx.tools
    subagents = SubagentRegistry(ctx)
    subagents.register_provider(InProcessSubagentProvider("in-process", inherits_parent_context=False))
    subagents.register_provider(InProcessSubagentProvider("fork", inherits_parent_context=True))
    _load_agents(root, subagents)
    tools.register(make_task_tool(subagents))


def _apply_agents_md(ctx, root: Path):
    agents_md = root / "AGENTS.md"
    if agents_md.is_file():
        ctx.systemPrompt.section("workspace", agents_md.read_text(encoding="utf-8"), order=0)


def _apply_persistence(ctx, root: Path, storage: str):
    storage_root = root / ".dsh"
    if storage == "sqlite":
        backend = SqliteSessionPersistence(storage_root)
    else:
        backend = JsonlSessionPersistence(storage_root)
    ctx.provide("sessionPersistence", PersistenceCoordinator(ctx, backend))
    ctx._persistence_backend = backend


BASE_PLUGIN_FACTORIES = build_base_plugins

# base 清单：激活顺序（依赖由 inject 保证，这里列的是「声明激活」的意图）。
base_manifest = [
    {"name": "minidsh.config"},
    {"name": "minidsh.sessions"},
    {"name": "minidsh.llm"},
    {"name": "minidsh.prompt"},
    {"name": "minidsh.tools"},
    {"name": "minidsh.shell"},
    {"name": "minidsh.fs"},
    {"name": "minidsh.tool-bash"},
    {"name": "minidsh.tool-read"},
    {"name": "minidsh.skills"},
    {"name": "minidsh.subagents"},
    {"name": "minidsh.agents-md"},
    {"name": "minidsh.loop"},
    {"name": "minidsh.compaction"},
    {"name": "minidsh.trace-render"},
    {"name": "minidsh.persistence"},
]