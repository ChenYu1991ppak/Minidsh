"""base 插件：trace-render（ConsoleRenderer）。"""
from __future__ import annotations

from .renderer import ConsoleRenderer

name = "pydsh.trace-render"
inject = ["sessions"]


def apply(ctx):
    ctx._renderer = ConsoleRenderer(ctx)
