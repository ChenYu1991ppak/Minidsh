"""激活：plugins 名单 + resolver → 装配完成的 Context。"""
from __future__ import annotations

from typing import Any, Callable

from ...cordis import Context
from .bundle import PluginRef

__all__ = ["build_context"]

Resolver = Callable[[str], Any]  # name → 插件可调用对象（module/Plugin），未找到返回 None


def build_context(
    plugins: list[PluginRef],
    resolver: Resolver,
    *,
    ctx: Context | None = None,
) -> Context:
    """按 plugins 名单顺序激活插件，返回 Context。

    - ``resolver``：name → 插件可调用对象；未找到（返回 None）则告警跳过。
    - 每个条目：找到插件 → ctx.plugin(plugin, config=ref.config)；未找到 → 告警跳过。
    """
    ctx = ctx if ctx is not None else Context()
    for ref in plugins:
        plugin_obj = resolver(ref.name)
        if plugin_obj is None:
            _warn(f"引用了未知插件 {ref.name!r}，跳过")
            continue
        ctx.plugin(plugin_obj, config=ref.config)
    return ctx


def _warn(msg: str) -> None:
    import sys

    print(f"[minidsh] 警告：{msg}", file=sys.stderr)