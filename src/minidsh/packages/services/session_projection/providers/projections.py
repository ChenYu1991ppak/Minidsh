"""base 插件：projections（提供 ctx.sessionProjections + 注册 lastMessage 单元）。"""
from __future__ import annotations

from minidsh.packages.services.session_projection import (
    SessionProjectionRegistry,
    make_last_message_unit,
)

name = "minidsh.projections"
inject = ["sessions"]


def apply(ctx):
    registry = SessionProjectionRegistry(ctx)  # 构造即注册 ctx.sessionProjections
    registry.register(make_last_message_unit())