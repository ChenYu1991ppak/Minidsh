"""项目加载器：把项目目录装配成完整能力图。

装配方式（全声明式，对齐官方 bundle）：
- 内置 base 清单 = 随包 `_bundles/base/base.yaml`（17 个插件名）；
- 内置 base + 第三方插件同一发现机制：entry-point 组 `minidsh.plugins`（条目名 = 插件名）；
- config/root 是运行时值（models.json/settings.json / CLI dir），经 `minidsh.config`
  / `minidsh.root` 两个插件的 ``SET`` 槽注入；
- 层叠 = 内置 base.yaml ← 项目 .minidsh/manifest.yaml ← 用户 ~/.minidsh/manifest.yaml ← argv。

resolver：统一走 entry_point_resolver（内置与第三方无差别）。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ...cordis import Context
from ...infrastructure.config import Config, resolve_config
from ...infrastructure.manifest import ManifestEntry, load_manifest, build_context
from ...infrastructure.packaging import entry_point_resolver
from ...infrastructure.config.providers import config as config_plugin
from ...applications.workspace.providers import root as root_plugin

__all__ = ["load_project"]


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

    # 内置清单：随包 base.yaml 的 17 个静态插件名；quiet 时剔除 trace-render
    builtin = _builtin_entries(quiet)

    if manifest_entries is not None:
        entries = manifest_entries
    else:
        entries = load_manifest(builtin=builtin, project_dir=root, argv_path=manifest_path)

    # 统一 resolver：内置 base 与第三方插件同走 entry-point 发现（无 registry）
    resolver = extra_resolver if extra_resolver is not None else entry_point_resolver()
    return build_context(cfg, entries, resolver)


def _builtin_entries(quiet: bool) -> list[ManifestEntry]:
    """内置激活清单（随包 base.yaml 的 17 个插件名；quiet 时剔 trace-render）。"""
    from ..._bundles.base import BASE_MANIFEST_NAMES

    return [
        ManifestEntry(name)
        for name in BASE_MANIFEST_NAMES
        if not (quiet and name == "minidsh.trace-render")
    ]