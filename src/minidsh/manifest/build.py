"""build_context：manifest + resolver → 装配完成的 Context。"""
from __future__ import annotations

from typing import Any, Callable

from ..cordis import Context, normalize_plugin
from .schema import ManifestEntry, Resolver

__all__ = ["build_context"]


def build_context(
    config: Any,
    manifest: list[ManifestEntry],
    resolver: Resolver,
    *,
    ctx: Context | None = None,
) -> Context:
    """按清单顺序激活插件，返回 Context。

    - ``config``：minidsh Config（传给需要它的插件装配逻辑的上下文；本函数仅透传，
      具体插件经闭包读取——插件注册用闭包而非 config 注入）。
    - ``resolver``：name → 插件可调用对象；未找到（返回 None）则该条目**告警跳过**。
    - ``ctx``：可复用已有 Context（默认为新建）。

    每个条目：
      找到插件 → normalize → ctx.plugin(plugin, config=entry.config)；末找到 → 告警跳过。
    """
    ctx = ctx if ctx is not None else Context()
    for entry in manifest:
        plugin_obj = resolver(entry.name)
        if plugin_obj is None:
            _warn(f"manifest 引用了未知插件 {entry.name!r}，跳过")
            continue
        ctx.plugin(plugin_obj, config=entry.config)
    return ctx


def _warn(msg: str) -> None:
    import sys

    print(f"[minidsh] 警告：{msg}", file=sys.stderr)