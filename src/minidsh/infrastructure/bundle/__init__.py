"""bundle 模块：一等 bundle 概念 + plugins 列表代数 + 激活。"""
from __future__ import annotations

from .bundle import (
    PluginRef,
    Bundle,
    parse_plugins,
    merge_plugins,
    apply_removes,
    load_bundle,
    BUILTIN_BUNDLE_NAME,
)
from .build import build_context

__all__ = [
    "PluginRef",
    "Bundle",
    "parse_plugins",
    "merge_plugins",
    "apply_removes",
    "load_bundle",
    "build_context",
    "BUILTIN_BUNDLE_NAME",
]