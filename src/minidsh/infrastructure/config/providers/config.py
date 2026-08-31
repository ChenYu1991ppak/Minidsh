"""base 插件：config（提供 ctx.config）。

config 是运行时值（由 models.json/settings.json 三级链解析），无法进 yaml；loader 在激活
前把已解析 Config 写入本模块的 ``SET`` 槽，apply 读槽 provide。
"""
from __future__ import annotations

name = "minidsh.config"
inject: list[str] = []

SET = None  # loader 在激活前写入已解析的 Config


def apply(ctx):
    ctx.provide("config", SET)
