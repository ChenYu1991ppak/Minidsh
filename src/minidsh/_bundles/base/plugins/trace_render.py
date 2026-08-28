"""base 插件：trace-render（ConsoleRenderer）。"""
from __future__ import annotations

from minidsh.applications.trace import ConsoleRenderer

name = "minidsh.trace-render"
inject = ["sessions"]


def apply(ctx):
    ctx._renderer = ConsoleRenderer(ctx)
