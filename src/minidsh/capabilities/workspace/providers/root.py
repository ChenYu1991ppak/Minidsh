"""base 插件：root（提供 ctx.root，项目根 Path）。

root 是运行时值（CLI 的 dir 参数），无法进 yaml；loader 在激活前把项目根 Path 写入
本模块的 ``SET`` 槽，apply 读槽 provide。
"""
from __future__ import annotations

name = "minidsh.root"
inject: list[str] = []

SET = None  # loader 在激活前写入项目根 Path


def apply(ctx):
    ctx.provide("root", SET)
