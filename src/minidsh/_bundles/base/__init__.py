"""内置 base 插件包（对官方「bundle = 数据 + 静态插件」）。

- ``base.yaml``：内置激活清单（声明「激活哪些插件」）
- ``registry.py``：内置插件名 → module 的静态映射（供 loader 的 resolver 基线）

各插件的 ``apply``（name/inject/provider 服务）落在对应能力的 ``providers/`` 子目录，
不集中在这里。config / root 是带 ``SET`` 槽的运行时值插件，loader 装配前注入。
"""
from __future__ import annotations

from .registry import builtin_registry

__all__ = ["builtin_registry"]