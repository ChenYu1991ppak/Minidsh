"""项目加载器：把项目目录装配成完整能力图。

对应源码（ch08 的 workspace/context + ch15 的 boot 组合）：
- AGENTS.md 全文 → systemPrompt 节（workspace instructions）
- models.json → 模型配置（对齐 CodeBuddy，内嵌 apiKey）+ 当前模型选择
- settings.json → harness 设置（storage/compaction/工具白名单）
- skills/<name>/SKILL.md → FilesystemSkillProvider
- agents/<name>.md → subagent 定义（frontmatter name/description + 正文）

装配方式（manifest 化）：能力分解为内置 base 具名插件（``minidsh._bundles.base``），
经 ``manifest.load_manifest`` 合并层叠（内置 ← 项目 .minidsh/manifest.yaml ← 用户
~/.minidsh/manifest.yaml），再 ``manifest.build_context`` 按序激活。

resolver：name → 插件（base 插件 + 第三方 entry-point 插件，见 packaging 模块）。
本 loader 只定义装配入口，不硬编码业务插件。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ..cordis import Context
from ..config import Config, resolve_config
from ..manifest import ManifestEntry, load_manifest, build_context
from .._bundles.base import build_base_plugins, base_manifest

__all__ = ["load_project"]


def _make_resolver(base_plugins: dict[str, Any], extra_resolver=None):
    """name → 插件：先查 base 插件，再查 extra（entry-point 发现，packaging 提供）。"""

    def resolver(name: str):
        plugin = base_plugins.get(name)
        if plugin is not None:
            return plugin
        if extra_resolver is not None:
            return extra_resolver(name)
        return None

    return resolver


def load_project(
    project_dir: str | Path,
    *,
    config: Config | None = None,
    storage: str | None = None,
    quiet: bool = False,
    llm_client: Any | None = None,
    manifest_entries: list[ManifestEntry] | None = None,
    manifest_path: str | Path | None = None,
    extra_resolver=None,
) -> Context:
    """加载项目目录，装配能力图，返回 Context。

    - ``config``：已解析配置；为 None 时用 ``resolve_config(project_dir)`` 解析。
    - ``storage``：CLI 覆盖持久化后端（jsonl | sqlite）。
    - ``llm_client``：测试注入的假 client。
    - ``manifest_entries``：（测试用）显式清单，跳过文件层叠。
    - ``manifest_path``：argv 覆盖层清单文件（优先级最高）。
    - ``extra_resolver``：第三方插件查找器（packaging 提供 entry-point 发现）。
    """
    root = Path(project_dir).resolve()
    cfg = config if config is not None else resolve_config(root)
    if storage is not None:
        cfg = replace(cfg, storage=storage)

    # 内置 base 插件（按配置生成） + 内置清单（quiet 时剔除 trace-render）
    base_plugins = build_base_plugins(root, cfg, llm_client, quiet)
    builtin = [
        ManifestEntry(e["name"]) for e in base_manifest
        if not (quiet and e["name"] == "minidsh.trace-render")
    ]

    if manifest_entries is not None:
        entries = manifest_entries
    else:
        entries = load_manifest(builtin=builtin, project_dir=root, argv_path=manifest_path)

    resolver = _make_resolver(base_plugins, extra_resolver)
    return build_context(cfg, entries, resolver)