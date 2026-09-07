"""base 插件：tools（空 ToolRuntime；bash/read_file 由 consumer 注册）。"""
from __future__ import annotations

from minidsh.packages.services.tool_runtime import ToolRuntime

name = "minidsh.tools"
inject: list[str] = []


def apply(ctx):
    ToolRuntime(ctx)
