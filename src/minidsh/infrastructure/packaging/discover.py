"""插件发现：entry-point 组 ``minidsh.plugins``（对齐官方 npm bundle 的 Python 版）。

第三方包在 pyproject.toml 声明：
    [project.entry-points."minidsh.plugins"]
    my-tool-plugin = "my_tool_plugin"          # 值为「可 import 模块」（含 name/inject/apply）

发现逻辑：经 ``importlib.metadata.entry_points(group=...)`` 枚举，条目 name 即插件
name（对应官方 ``export const name``），值 import 为模块后经 normalize_plugin 归一。

resolver 契约：``entry_point_resolver()`` 返回 name → 插件可调用对象 的查找器，供
bundle.build_context 使用；未找到返回 None。
"""
from __future__ import annotations

import importlib
import importlib.metadata as _metadata
from typing import Any, Callable

from ...cordis import normalize_plugin

__all__ = ["discover_plugins", "entry_point_resolver"]

ENTRY_POINT_GROUP = "minidsh.plugins"


def _load_entry_point(ep) -> Any | None:
    """加载一个 entry point 的值为可调用对象/模块/Plugin。

    值必须形如 ``pkg.module``（模块，含 name/inject/apply）；模块内的 name/inject/apply
    由 normalize_plugin（module 形态）提取。加载失败返回 None（不阻断发现）。
    """
    try:
        module = importlib.import_module(ep.value)
    except (ImportError, AttributeError):
        return None
    try:
        return normalize_plugin(module)
    except TypeError:
        return None


def discover_plugins() -> dict[str, Any]:
    """枚举组内全部插件，返回 {插件名 → 归一化 Plugin}。条目 name 即插件名。"""
    found: dict[str, Any] = {}
    eps = _metadata.entry_points(group=ENTRY_POINT_GROUP)
    for ep in eps:
        plugin = _load_entry_point(ep)
        if plugin is not None:
            found[ep.name] = plugin
    return found


def entry_point_resolver() -> Callable[[str], Any]:
    """返回 name → 插件 的查找器（供 bundle.build_context）。

    每次调用 resolver 时惰性发现一次并缓存（发现成本一次性）。
    """
    cache: dict[str, Any] = {}

    def resolver(name: str) -> Any:
        if not cache:
            cache.update(discover_plugins())
        return cache.get(name)

    return resolver