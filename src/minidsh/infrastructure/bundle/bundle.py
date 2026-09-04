"""bundle 一等概念 + plugins 列表代数。

对齐官方 bundle：一个 bundle = 名字 + 一份 plugins 声明（直接列插件，无中间「清单」概念）。
``PluginRef`` 是「激活一个插件」的最小条目；``merge_plugins`` / ``apply_removes`` 是
plugins 列表的纯函数组合，供 bundle 展开与 profile 覆盖共用。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "PluginRef",
    "Bundle",
    "parse_plugins",
    "merge_plugins",
    "apply_removes",
    "load_bundle",
    "BUILTIN_BUNDLE_NAME",
]

BUILTIN_BUNDLE_NAME = "minidsh.base"
_BUNDLES_DIR = Path(__file__).resolve().parent.parent.parent / "bundles"


@dataclass(frozen=True)
class PluginRef:
    """激活一个插件的条目：名字 + 可选 config。"""

    name: str
    config: dict | None = None


@dataclass(frozen=True)
class Bundle:
    """一个 bundle：名字 + 它激活哪些插件（plugins）+ 移除哪些（remove）。"""

    name: str
    plugins: list[PluginRef]
    remove: list[str] = ()


def parse_plugins(text: str) -> tuple[list[PluginRef], list[str]]:
    """解析含 ``plugins:`` / ``remove:`` 的 YAML 文本 → (plugins, remove)。

    bundle 文件与 profile 文件共用此格式（顶层两个键）。
    """
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("bundle/profile 必须是 mapping（顶层 plugins:/remove: 键）")

    raw_plugins = data.get("plugins") or []
    if not isinstance(raw_plugins, list):
        raise ValueError("plugins 必须是列表")
    plugins: list[PluginRef] = []
    for item in raw_plugins:
        if isinstance(item, str):
            plugins.append(PluginRef(name=item))
        elif isinstance(item, dict):
            name = item.get("name")
            if not name:
                raise ValueError(f"plugin 条目缺少 name：{item!r}")
            cfg = item.get("config")
            plugins.append(PluginRef(name=name, config=cfg if isinstance(cfg, dict) else None))
        else:
            raise ValueError(f"plugin 条目类型非法：{item!r}")

    removes = data.get("remove") or []
    if not isinstance(removes, list) or not all(isinstance(x, str) for x in removes):
        raise ValueError("remove 必须是字符串列表")
    return plugins, removes


def merge_plugins(layers: list[list[PluginRef]]) -> list[PluginRef]:
    """合并多层 plugins：后层追加，同 name 由后层整体替换前层那条（累加语义）。"""
    ordered: dict[str, int] = {}
    result: list[PluginRef] = []
    for layer in layers:
        for ref in layer:
            if ref.name in ordered:
                result[ordered[ref.name]] = ref
            else:
                ordered[ref.name] = len(result)
                result.append(ref)
    return result


def apply_removes(plugins: list[PluginRef], removes: list[str]) -> list[PluginRef]:
    """全局移除：凡 name 命中 removes 的条目剔除。"""
    if not removes:
        return plugins
    blacklist = set(removes)
    return [r for r in plugins if r.name not in blacklist]


def load_bundle(name: str) -> Bundle | None:
    """按名加载 bundle。

    v1 支持内置 bundle：读 ``bundles/<name>.yaml``（含 ``minidsh.base`` 与
    ``minidsh.tui-textual`` 等前端 bundle）。第三方 bundle 后续接 entry-point /
    文件发现，同归一为 Bundle。

    未找到返回 None（调用方决定是否报错）。
    """
    return _load_bundle_file(_BUNDLES_DIR / f"{name}.yaml")


def _load_bundle_file(path: Path) -> Bundle | None:
    if not path.is_file():
        return None
    plugins, removes = parse_plugins(path.read_text(encoding="utf-8"))
    return Bundle(name=path.stem, plugins=plugins, remove=removes)