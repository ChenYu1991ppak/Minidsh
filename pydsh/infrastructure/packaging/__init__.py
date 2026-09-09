"""packaging 模块：插件发现 + 安装命令。"""
from __future__ import annotations

from .discover import discover_plugins, entry_point_resolver, ENTRY_POINT_GROUP
from .plugin_cmd import plugin_add, plugin_remove, plugin_list

__all__ = [
    "discover_plugins",
    "entry_point_resolver",
    "ENTRY_POINT_GROUP",
    "plugin_add",
    "plugin_remove",
    "plugin_list",
]