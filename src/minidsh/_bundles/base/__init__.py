"""内置 base 插件包（对官方「bundle = 数据 + 静态插件」）。

- ``base.yaml``：内置激活清单（声明「激活哪些插件」）
- 各插件的 ``apply`` 落在对应能力的 ``providers/``，经 entry-point 组 ``minidsh.plugins``
  与第三方插件同机制发现（无 registry）。

``BASE_MANIFEST_NAMES`` 从 base.yaml 解析出的插件名顺序，供 loader 构造内置激活清单；
config / root 是带 ``SET`` 槽的运行时值插件，loader 装配前注入。
"""
from __future__ import annotations

from pathlib import Path

from ...infrastructure.manifest import load_manifest_file

__all__ = ["BASE_MANIFEST_NAMES"]

_BASE_YAML = Path(__file__).parent / "base.yaml"


def _load_base_names() -> list[str]:
    entries, _removes = load_manifest_file(_BASE_YAML)
    return [e.name for e in entries]


BASE_MANIFEST_NAMES: list[str] = _load_base_names()