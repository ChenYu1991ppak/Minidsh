"""项目加载器：把项目目录装配成完整能力图。

装配方式（全声明式，对齐官方 bundle + profile）：
- profile 层 = 所选 bundles 的 manifest 有序合并（默认 [minidsh.base]）；
- 内置 base + 第三方插件同一发现机制：entry-point 组 `minidsh.plugins`（条目名 = 插件名）；
- config/root 是运行时值，经 `minidsh.config` / `minidsh.root` 两个插件的 ``SET`` 槽注入；
- 层叠 = profile 层 ← 项目 .minidsh/manifest.yaml ← 用户 ~/.minidsh/manifest.yaml ← argv。

resolver：统一走 entry_point_resolver（内置与第三方无差别）。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ...cordis import Context
from ...infrastructure.config import Config, resolve_config
from ...infrastructure.manifest import ManifestEntry, load_manifest, build_context
from ...infrastructure.packaging import entry_point_resolver
from ...infrastructure.profile import resolve_profile_manifest
from ...infrastructure.config.providers import config as config_plugin
from ...applications.workspace.providers import root as root_plugin

__all__ = ["load_project"]


def load_project(
    project_dir: str | Path,
    *,
    config: Config | None = None,
    storage: str | None = None,
    quiet: bool = False,
    profile: str | None = None,
    manifest_entries: list[ManifestEntry] | None = None,
    manifest_path: str | Path | None = None,
    extra_resolver=None,
) -> Context:
    """加载项目目录，装配能力图，返回 Context。

    - ``config``：已解析配置；为 None 时用 ``resolve_config(project_dir)`` 解析。
    - ``storage``：CLI 覆盖持久化后端（jsonl | sqlite）。
    - ``profile``：profile 名；None = 默认 [minidsh.base]。
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

    # profile 层（合并所选 bundles 的 manifest）；quiet 时剔除 trace-render
    builtin = _profile_entries(profile, quiet)

    if manifest_entries is not None:
        entries = manifest_entries
    else:
        entries = load_manifest(builtin=builtin, project_dir=root, argv_path=manifest_path)

    # 统一 resolver：内置 base 与第三方插件同走 entry-point 发现（无 registry）
    resolver = extra_resolver if extra_resolver is not None else entry_point_resolver()
    return build_context(cfg, entries, resolver)


def _profile_entries(profile: str | None, quiet: bool) -> list[ManifestEntry]:
    """解析 profile → 合并的 profile 层清单；quiet 时剔除 trace-render。"""
    merged = resolve_profile_manifest(profile)
    return [
        e for e in merged
        if not (quiet and e.name == "minidsh.trace-render")
    ]