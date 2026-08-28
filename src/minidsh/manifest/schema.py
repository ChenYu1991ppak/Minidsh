"""manifest 模块：装配清单 schema + 各层合并 + build_context。

对齐官方 cordis.yml overlay 的「声明装配、非硬编码」语义（Python 版，manifest.yaml）。

清单 schema（SPEC-manifest §2.1）：
    plugins:
      - name: minidsh.sessions
      - name: my-third-party-plugin
        config: { threshold: 0.8 }

层叠（§2.2，后层 win per row）：
    内置默认 ← 项目 .minidsh/manifest.yaml ← 用户 ~/.minidsh/manifest.yaml ← argv --manifest
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

__all__ = ["ManifestEntry", "load_manifest", "merge_manifests"]

Resolver = Callable[[str], Any]  # name → 插件可调用对象（module/Plugin），未找到返回 None


@dataclass(frozen=True)
class ManifestEntry:
    """一条装配条目。"""

    name: str
    config: dict | None = None


def parse_manifest(text: str) -> list[ManifestEntry]:
    """解析 YAML 文本 → 有序条目列表。空/非法返回空列表（解析失败向上抛异常）。"""
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest 必须是 mapping（顶层 plugins: 列表）")
    plugins = data.get("plugins", [])
    if plugins is None:
        return []
    if not isinstance(plugins, list):
        raise ValueError("manifest.plugins 必须是列表")
    entries: list[ManifestEntry] = []
    for item in plugins:
        if isinstance(item, str):
            entries.append(ManifestEntry(name=item))
        elif isinstance(item, dict):
            name = item.get("name")
            if not name:
                raise ValueError(f"manifest 条目缺少 name：{item!r}")
            config = item.get("config")
            entries.append(ManifestEntry(name=name, config=config if isinstance(config, dict) else None))
        else:
            raise ValueError(f"manifest 条目类型非法：{item!r}")
    return entries


def load_manifest_file(path: str | Path) -> list[ManifestEntry]:
    """读一个 manifest 文件；缺失返回空列表。"""
    p = Path(path)
    if not p.is_file():
        return []
    return parse_manifest(p.read_text(encoding="utf-8"))


def merge_manifests(layers: list[list[ManifestEntry]]) -> list[ManifestEntry]:
    """合并多层清单：后层追加，同 name 由后层整体替换前层那条。

    layers[0] 最低（内置默认），layers[-1] 最高（argv）。返回有序合并结果。
    """
    ordered: dict[str, int] = {}  # name → 位置索引（保序）
    result: list[ManifestEntry] = []
    for layer in layers:
        for entry in layer:
            if entry.name in ordered:
                result[ordered[entry.name]] = entry  # 整体替换
            else:
                ordered[entry.name] = len(result)
                result.append(entry)
    return result


def load_manifest(
    builtin: list[ManifestEntry] | None = None,
    project_dir: str | Path | None = None,
    user_home: str | Path | None = None,
    argv_path: str | Path | None = None,
) -> list[ManifestEntry]:
    """按层叠加载合并：内置 → 项目 → 用户 → argv。"""
    from ..config.files import user_config_dir

    layers: list[list[ManifestEntry]] = [builtin or []]
    if project_dir is not None:
        layers.append(load_manifest_file(Path(project_dir) / ".minidsh" / "manifest.yaml"))
    home = Path(user_home) if user_home else user_config_dir()
    layers.append(load_manifest_file(home / "manifest.yaml"))
    if argv_path is not None:
        layers.append(load_manifest_file(argv_path))
    return merge_manifests(layers)