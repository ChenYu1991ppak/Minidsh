"""项目加载器：把项目目录装配成完整能力图。

装配方式（对齐官方 bundle + profile）：
- profile 覆盖链（默认 [minidsh.base] < 命名 < 项目 < 用户 < argv）得到最终 plugins 名单；
- 内置 base + 第三方插件同一发现机制：entry-point 组 `minidsh.plugins`（条目名 = 插件名）；
- config/root 是运行时值，经 `minidsh.config` / `minidsh.root` 两个插件的 ``SET`` 槽注入。

resolver：统一走 entry_point_resolver（内置与第三方无差别）。
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ...cordis import Context
from ..config import Config, resolve_config
from ..bundle import PluginRef, build_context
from ..packaging import entry_point_resolver
from ..profile import resolve_profile
from ..config.providers import config as config_plugin
from ...packages.services.workspace.providers import root as root_plugin

__all__ = ["load_project"]


def load_project(
    project_dir: str | Path,
    *,
    config: Config | None = None,
    storage: str | None = None,
    quiet: bool = False,
    profile: str | None = None,
    plugins: list[PluginRef] | None = None,
    argv_path: str | Path | None = None,
    extra_resolver=None,
) -> Context:
    """加载项目目录，装配能力图，返回 Context。

    - ``config``：已解析配置；为 None 时用 ``resolve_config(project_dir)`` 解析。
    - ``storage``：CLI 覆盖持久化后端（jsonl | sqlite）。
    - ``profile``：profile 名（或路径）；None = 默认 [minidsh.base]。
    - ``plugins``：（测试用）显式 plugins 名单，跳过覆盖链。
    - ``argv_path``：argv 覆盖 profile 文件（优先级最高）。
    - ``extra_resolver``：第三方插件查找器（entry-point 发现）。
    """
    root = Path(project_dir).resolve()
    cfg = config if config is not None else resolve_config(root)
    if storage is not None:
        cfg = replace(cfg, storage=storage)

    # 注入 config/root 运行时值（经 SET 槽，非闭包）
    config_plugin.SET = cfg
    root_plugin.SET = root

    # profile 覆盖链得到最终 plugins 名单；quiet 时剔除 trace-render
    if plugins is not None:
        entries = plugins
    else:
        entries = _profile_plugins(profile, root, argv_path, quiet)

    # storage 覆盖：持久化 provider 是平级插件（jsonl/sqlite），CLI --storage 转成
    # 「移除未选中的、追加选中的」——provider 选择走清单，不走进 provider 内部 if 分支。
    if storage is not None:
        entries = _select_persistence(entries, storage)

    # 统一 resolver：内置 base 与第三方插件同走 entry-point 发现（无 registry）
    resolver = extra_resolver if extra_resolver is not None else entry_point_resolver()
    return build_context(entries, resolver)


_PERSISTENCE_PROVIDERS = {
    "jsonl": "minidsh.persistence-jsonl",
    "sqlite": "minidsh.persistence-sqlite",
}


def _select_persistence(entries: list[PluginRef], storage: str) -> list[PluginRef]:
    """按所选后端（jsonl|sqlite）从激活清单里去掉其它持久化 provider、追加所选。

    结果保序：原名单中非 persistence 的条目不变，选中的 persistence provider 追加到末尾。
    """
    if storage not in _PERSISTENCE_PROVIDERS:
        return entries
    chosen = _PERSISTENCE_PROVIDERS[storage]
    others = {n for k, n in _PERSISTENCE_PROVIDERS.items() if k != storage}
    filtered = [r for r in entries if r.name not in others]
    if not any(r.name == chosen for r in filtered):
        filtered.append(PluginRef(chosen))
    return filtered


def _profile_plugins(
    profile: str | None,
    root: Path,
    argv_path: str | Path | None,
    quiet: bool,
) -> list[PluginRef]:
    """解析覆盖链 → 最终 plugins 名单；quiet 时剔除 trace-render。"""
    merged = resolve_profile(profile=profile, project_dir=root, argv_path=argv_path)
    return [
        r for r in merged
        if not (quiet and r.name == "minidsh.trace-render")
    ]