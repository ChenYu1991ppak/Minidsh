"""Service：服务基类，构造即注册。

源码对应：vendor/cordis/src/service.ts:11：构造器调 ctx.reflect.provide（:57）把实例
挂到 ctx.<key>。

教学版用 ctx.effect 显式表达「卸载即移除」——注册本身就是可逆效应。
"""
from __future__ import annotations

__all__ = ["Service"]


class Service:
    """服务基类：构造时注册到容器，卸载时移除。"""

    def __init__(self, ctx, name=None):
        self.ctx = ctx
        self.service_name = name
        if name is not None:
            dispose = ctx.provide(name, self)
            ctx.effect(lambda: dispose, label=f"service:{name}")