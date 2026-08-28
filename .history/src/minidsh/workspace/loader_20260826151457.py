"""项目加载器：把项目目录装配成完整能力图。

对应源码（ch08 的 workspace/context + ch15 的 boot 组合）：
- AGENTS.md 全文 → systemPrompt 节（workspace instructions）
- dsh.toml → 非密配置（provider/model/base_url/storage/compaction/工具白名单）
- skills/<name>/SKILL.md → FilesystemSkillProvider
- agents/<name>.md → subagent 定义（frontmatter name/description + 正文）

配置来源：``minidsh.config.resolve_config(project_dir)`` 三级链（env → dsh.toml →
用户级 config.toml + credentials）。密钥不进 dsh.toml。

装配方式（§一切皆插件）：每个能力都是一个插件，经 ``ctx.plugin`` 注册产出 Fiber，
用 ``inject`` 声明依赖，依赖齐备才激活；依赖被替换时 Fiber 自动重载。配置经闭包
注入插件体（config 不进 Fiber 的 config 参数，闭包更直白）。装配顺序即依赖方向，
由 inject 声明驱动，而非代码书写顺序。

依赖方向（§plan）：sessions/llm/prompt/tools（无依赖）→ skills/subagents（依赖
tools/prompt）→ agent_loop（依赖 sessions/llm/prompt/tools）→ compaction（依赖
sessions/llm）→ trace 渲染 + 持久化（依赖 sessions）。
"""
from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..cordis import Context
from ..session import SessionStore
from ..session.persistence import PersistenceCoordinator
from ..session.persistence_jsonl import JsonlSessionPersistence
from ..session.persistence_sqlite import SqliteSessionPersistence
from ..llm import OpenAILlm
from ..prompt import SystemPromptService
from ..tools import ToolRuntime, bash_tool, read_file_tool
from ..skills import FilesystemSkillProvider, SkillRegistry, make_catalog_tool
from ..subagent import (
    SubagentRegistry,
    InProcessSubagentProvider,
    make_task_tool,
)
from ..loop import AgentLoop
from ..compaction import CompactionEngine
from ..trace import ConsoleRenderer
from ..config import Config, resolve_config

__all__ = ["load_project"]


def _read_tool_whitelist(root: Path) -> list[str] | None:
    """读 dsh.toml 的 ``[tools] allow``（项目级工具白名单，非 Config 五键）。"""
    dsh = root / "dsh.toml"
    if not dsh.is_file():
        return None
    try:
        data = tomllib.loads(dsh.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tools = data.get("tools", {})
    if isinstance(tools, dict) and isinstance(tools.get("allow"), list):
        return [str(x) for x in tools["allow"]]
    return None


def _parse_agent_md(text: str) -> tuple[str, str, str] | None:
    """解析 agents/<name>.md 的 frontmatter（name/description）+ 正文。"""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
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


def _build_llm(cfg: Config, llm_client: Any | None):
    """按 provider 建造 LlmRuntime。

    v1 只实现 openai；anthropic 是 seam 预留，抛清晰错误。
    ``llm_client`` 供测试注入假 client（跳过真实 SDK 连接）。
    """
    if cfg.provider == "openai":
        return OpenAILlm(
            model=cfg.model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            client=llm_client,
        )
    raise NotImplementedError(
        f"provider {cfg.provider!r} 尚未实现；当前仅支持 openai（seam 已为 anthropic 预留）"
    )


def load_project(
    project_dir: str | Path,
    *,
    config: Config | None = None,
    storage: str | None = None,
    quiet: bool = False,
    llm_client: Any | None = None,
) -> Context:
    """加载项目目录，按依赖顺序装配各能力插件，返回可用的 Context。
    
    负责把 LLM、会话存储、系统提示词、工具、技能、子代理、workspace 指令、AgentLoop、
    压缩、追踪渲染与持久化等模块，按注入依赖关系注册进 Context。
    
    Args:
        project_dir (str | Path): 项目根目录，内部会解析为绝对路径。
        config (Config | None): 已解析配置；为 None 时用 ``resolve_config(root)`` 三级链解析。
        storage (str | None): CLI 覆盖的持久化后端（jsonl | sqlite）；提供时替换配置中的 storage。
        quiet (bool): 为 True 时跳过 trace 渲染插件。
        llm_client (Any | None): 测试注入的假 client，跳过真实 OpenAI 连接；为 None 时按配置构建真实 client。
    
    Returns:
        Context: 装配完成、各能力已注入的上下文对象。
    
    Raises:
        ConfigError: 配置解析失败时抛出（由 ``resolve_config`` 或配置校验触发）。
    """
    """加载项目目录，返回装配完成的 Context。

    - ``config``：已解析配置；为 None 时用 ``resolve_config(project_dir)`` 三级链解析。
    - ``storage``：CLI 覆盖持久化后端（jsonl | sqlite）。
    - ``llm_client``：测试注入的假 client（跳过真实 OpenAI 连接）。
    """
    root = Path(project_dir).resolve()
    cfg = config if config is not None else resolve_config(root)
    if storage is not None:
        cfg = replace(cfg, storage=storage)

    ctx = Context()

    # ---- 无依赖能力（pluin 注册，inject=[] 立即激活）----
    ctx.plugin(lambda ctx: ctx.provide("sessions", SessionStore(ctx)))
    ctx.plugin(lambda ctx: ctx.provide("llm", _build_llm(cfg, llm_client)))
    ctx.plugin(lambda ctx: ctx.provide("systemPrompt", SystemPromptService(ctx)))
    ctx.plugin(_tools_plugin(root))

    # ---- skills / subagents（依赖 tools，经 inject 声明）----
    ctx.plugin(_skills_plugin(root))

    # ---- workspace 指令（AGENTS.md）注入 systemPrompt（依赖 systemPrompt）----
    ctx.plugin(_agents_md_plugin(root))

    # ---- loop（依赖 sessions/llm/systemPrompt/tools，构造即注册 ctx.agent_loop）----
    ctx.plugin(AgentLoop)

    # ---- compaction（依赖 sessions/llm）----
    ctx.plugin(_compaction_plugin(cfg))

    # ---- trace 渲染（观测，依赖 sessions）----
    if not quiet:
        ctx.plugin(_renderer_plugin())

    # ---- 持久化（依赖 sessions，订阅 session/event 写盘）----
    ctx.plugin(_persistence_plugin(root, cfg.storage))

    return ctx


def _tools_plugin(root: Path):
    """工具能力插件：注册 ToolRuntime + 内置工具 + catalog/task 委派工具。"""
    whitelist = _read_tool_whitelist(root)

    class ToolsPlugin:
        inject = []  # 无外部依赖

        def __init__(self, ctx, config=None):
            tools = ToolRuntime(ctx)  # 构造即注册 ctx.tools
            for definition in (read_file_tool, bash_tool):
                if whitelist is None or definition.name in whitelist:
                    tools.register(definition)

    return ToolsPlugin


def _skills_plugin(root: Path):
    """skills + subagents + task/catalog 工具装配插件（依赖 tools）。

    需在 tools 插件之后激活——但经 inject=["tools"] 声明，激活顺序自动保证，
    不依赖书写顺序。
    """

    class SkillsAndSubagentsPlugin:
        inject = ["tools"]

        def __init__(self, ctx, config=None):
            tools = ctx.tools
            # skills
            skills = SkillRegistry(ctx)  # 构造即注册 ctx.skills
            skills.register_provider(FilesystemSkillProvider(root))
            tools.register(make_catalog_tool(skills))
            # subagents
            subagents = SubagentRegistry(ctx)  # 构造即注册 ctx.subagents
            subagents.register_provider(
                InProcessSubagentProvider("in-process", inherits_parent_context=False)
            )
            subagents.register_provider(
                InProcessSubagentProvider("fork", inherits_parent_context=True)
            )
            _load_agents(root, subagents)
            tools.register(make_task_tool(subagents))

    return SkillsAndSubagentsPlugin


def _agents_md_plugin(root: Path):
    """AGENTS.md 全文注入 systemPrompt（依赖 systemPrompt）。"""

    class AgentsMdPlugin:
        inject = ["systemPrompt"]

        def __init__(self, ctx, config=None):
            _load_agents_md(root, ctx.systemPrompt)

    return AgentsMdPlugin


def _compaction_plugin(cfg: Config):
    """compaction 能力插件（依赖 sessions/llm，经 ctx.probe 取）。"""

    class CompactionPlugin:
        inject = ["sessions", "llm"]

        def __init__(self, ctx, config=None):
            ctx.provide(
                "compaction",
                CompactionEngine(
                    ctx,
                    context_window=cfg.context_window,
                    threshold_ratio=cfg.compaction_threshold_ratio,
                ),
            )

    return CompactionPlugin


def _renderer_plugin():
    """终端渲染插件（依赖 sessions；挂到 ctx 供测试取用）。"""

    class RendererPlugin:
        inject = ["sessions"]

        def __init__(self, ctx, config=None):
            ctx._renderer = ConsoleRenderer(ctx)

    return RendererPlugin


def _persistence_plugin(root: Path, storage: str):
    """持久化插件（依赖 sessions；订阅 session/event 写盘）。"""

    class PersistencePlugin:
        inject = ["sessions"]

        def __init__(self, ctx, config=None):
            storage_root = root / ".dsh"
            if storage == "sqlite":
                backend = SqliteSessionPersistence(storage_root)
            else:
                backend = JsonlSessionPersistence(storage_root)
            ctx.provide("sessionPersistence", PersistenceCoordinator(ctx, backend))
            ctx._persistence_backend = backend  # 供 CLI replay 关闭 sqlite 连接等

    return PersistencePlugin


def _load_agents(root: Path, subagents: SubagentRegistry):
    """扫 agents/*.md，登记子 agent 定义。"""
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    for path in sorted(agents_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed = _parse_agent_md(text)
        if parsed is not None:
            name, description, content = parsed
        else:
            name, description, content = path.stem, "", text  # 无 frontmatter：文件名 + 全文
        subagents.define_agent(name, {"name": name, "description": description, "content": content})


def _load_agents_md(root: Path, prompt: SystemPromptService):
    """AGENTS.md 全文作为一个系统提示节注入。"""
    agents_md = root / "AGENTS.md"
    if agents_md.is_file():
        prompt.section("workspace", agents_md.read_text(encoding="utf-8"), order=0)