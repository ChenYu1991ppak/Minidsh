"""项目加载器：把项目目录装配成完整能力图。

装配方式（全声明式，对齐官方 bundle）：
- 内置 base 清单 = 随包 `_bundles/base/base.yaml`（17 个静态插件名）；
- base 插件实现 = `_bundles/base/registry.py` 的 name→module 静态映射（+ capabilities 下
  shell/fs/tool），不闭包捕获 runtime 变量；
- config/root 是运行时值（models.json/settings.json / CLI dir），经 `minidsh.config`
  / `minidsh.root` 两个插件的 ``SET`` 槽注入；
- 第三方插件经 entry-point 组 `minidsh.plugins` 由 `extra_resolver` 发现；
- 层叠 = 内置 base.yaml ← 项目 .minidsh/manifest.yaml ← 用户 ~/.minidsh/manifest.yaml ← argv。

resolver：name → 插件（内置 registry 优先，其次第三方 entry-point）。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from ...cordis import Context
from ...infrastructure.config import Config, resolve_config
from ...infrastructure.manifest import ManifestEntry, load_manifest, build_context
from ..._bundles.base.registry import builtin_registry
from ...infrastructure.config.providers import config as config_plugin
from ...applications.workspace.providers import root as root_plugin

__all__ = ["load_project"]


def _make_resolver(base_plugins: dict[str, Any], extra_resolver=None):
    """name → 插件：先查内置 registry，再查第三方 entry-point。"""

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
    manifest_entries: list[ManifestEntry] | None = None,
    manifest_path: str | Path | None = None,
    extra_resolver=None,
) -> Context:
    """加载项目目录，装配能力图，返回 Context。

    - ``config``：已解析配置；为 None 时用 ``resolve_config(project_dir)`` 解析。
    - ``storage``：CLI 覆盖持久化后端（jsonl | sqlite）。
    - ``manifest_entries``：（测试用）显式清单，跳过文件层叠。
    - ``manifest_path``：argv 覆盖层清单文件（优先级最高）。
    - ``extra_resolver``：第三方插件查找器（entry-point 发现）。
    """
    root = Path(project_dir).resolve()
    cfg = config if config is not None else resolve_config(root)
    if storage is not None:
        cfg = replace(cfg, storage=storage)

    # 注入 config/root 运行时值（经 SET 槽，非闭包）
    config_plugin.SET = cfg
    root_plugin.SET = root

    base_plugins = builtin_registry()

    # 内置清单：随包 base.yaml 的 17 个静态插件名；quiet 时剔除 trace-render
    builtin = _builtin_entries(quiet)

    if manifest_entries is not None:
        entries = manifest_entries
    else:
        entries = load_manifest(builtin=builtin, project_dir=root, argv_path=manifest_path)

    resolver = _make_resolver(base_plugins, extra_resolver)
    return build_context(cfg, entries, resolver)


def _builtin_entries(quiet: bool) -> list[ManifestEntry]:
    """内置激活清单（含 17 插件名；quiet 时剔 trace-render）。"""
    from ..._bundles.base.registry import builtin_registry

    return [
        ManifestEntry(name)
        for name in builtin_registry()
        if not (quiet and name == "minidsh.trace-render")
    ]