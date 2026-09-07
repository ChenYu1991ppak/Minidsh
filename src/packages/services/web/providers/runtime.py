"""base 插件：web（提供 ctx.web 检索 seam）。

对齐官方 ``dsh-web`` 的 WebRuntime service：构造即注册 ``ctx.web``。
web-fetch-http / tool-web 等消费方经 ctx.web 注册 provider 或调用。
"""
from __future__ import annotations

from minidsh.packages.services.web import WebRuntime

name = "minidsh.web"
inject: list[str] = []


def apply(ctx):
    WebRuntime(ctx)  # 构造即注册 ctx.web
