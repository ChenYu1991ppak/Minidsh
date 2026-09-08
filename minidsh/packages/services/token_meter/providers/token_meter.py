"""base 插件：token-meter（提供 ctx.tokenMeter）。"""
from __future__ import annotations

from minidsh.packages.services.token_meter import TokenMeterService

name = "minidsh.token-meter"
inject = ["sessions"]


def apply(ctx):
    TokenMeterService(ctx)  # 构造即注册 ctx.tokenMeter