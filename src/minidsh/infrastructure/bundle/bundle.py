"""bundle 一等概念 + 内置 bundle 加载。

对齐官方 bundle：一个 bundle = 名字 + 一份 manifest（它激活哪些插件）。
``minidsh.base`` 是内置 bundle，manifest 随包在 ``bundles/minidsh.base/base.yaml``；
第三方 bundle 与它同形态（同样经 load_bundle 归一为 Bundle）。

设计（phase F）：loader 与 profile 都只消费 ``Bundle``，不含任何「哪个 bundle 特殊」的分支。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...infrastructure.manifest import ManifestEntry

__all__ = ["Bundle", "load_bundle", "BUILTIN_BUNDLE_NAME"]

BUILTIN_BUNDLE_NAME = "minidsh.base"

_BUNDLES_DIR = Path(__file__).resolve().parent.parent.parent / "bundles"


@dataclass(frozen=True)
class Bundle:
    """一个 bundle：名字 + 它激活哪些插件（有序 manifest）。"""

    name: str
    manifest: list[ManifestEntry]


def load_bundle(name: str) -> Bundle | None:
    """按名加载 bundle。

    v1 只支持内置 ``minidsh.base``（读 bundles/minidsh.base/base.yaml）。
    第三方 bundle 后续接 entry-point / 文件发现，同归一为 Bundle。

    未找到返回 None（调用方决定是否报错）。
    """
    if name == BUILTIN_BUNDLE_NAME:
        return _load_builtin_base()
    return None


def _load_builtin_base() -> Bundle:
    from ...infrastructure.manifest import load_manifest_file

    path = _BUNDLES_DIR / BUILTIN_BUNDLE_NAME / "base.yaml"
    entries, _removes = load_manifest_file(path)
    return Bundle(name=BUILTIN_BUNDLE_NAME, manifest=entries)