"""内置 base 插件包（对官方「bundle = 数据 + 静态插件」）。

- ``base.yaml``：内置激活清单（声明「激活哪些插件」）
- ``plugins/``：17 个静态 module 插件（name/inject/apply，读 ctx.config/ctx.root）
- ``registry.py``：内置插件名 → module 的静态映射（供 loader 的 resolver 基线）

config / root 是两个带 ``SET`` 槽的运行时值插件，loader 在装配前注入。
"""
from __future__ import annotations

from .registry import builtin_registry

__all__ = ["builtin_registry"]