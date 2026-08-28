"""manifest 模块：装配清单 schema + 各层合并 + build_context。

对齐官方 cordis.yml overlay 的「声明装配、非硬编码」语义（Python 版，manifest.yaml）。

清单 schema：
    plugins:
      - name: minidsh.sessions
      - name: my-third-party-plugin
        config: { threshold: 0.8 }
    remove:                      # 顶层键，全局移除（最强优先级）
      - minidsh.shell-local

层叠（后层 win per row）：
    内置默认 ← 项目 .minidsh/manifest.yaml ← 用户 ~/.minidsh/manifest.yaml ← argv --manifest

``remove`` 语义（SPEC-provider-select §2.2）：各层 plugins 合并完成后，凡 name 命中
任一层的 ``remove`` 列表，一律从最终结果剔除。用于「不激活 base 默认 provider」，
配合 plugins 追加替代 provider 完成「换 provider 只改清单」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

__all__ = ["ManifestEntry", "load_manifest", "merge_manifests", "parse_manifest"]

Resolver = Callable[[str], Any]  # name → 插件可调用对象（module/Plugin），未找到返回 None


@dataclass(frozen=True)
class ManifestEntry:
    """一条装配条目。"""

    name: str
    config: dict | None = None


def parse_manifest(text: str) -> tuple[list[ManifestEntry], list[str]]:
    """解析 YAML 文本 → (plugins 条目列表, remove 名单)。

    空/非法返回 ([], [])（解析失败向上抛异常）。
    """
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest 必须是 mapping（顶层 plugins:/remove: 键）")

    plugins = data.get("plugins", [])
    if plugins is None:
        plugins = []
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

    removes = data.get("remove", [])
    if removes is None:
        removes = []
    if not isinstance(removes, list) or not all(isinstance(x, str) for x in removes):
        raise ValueError("manifest.remove 必须是字符串列表")
    return entries, removes


def load_manifest_file(path: str | Path) -> tuple[list[ManifestEntry], list[str]]:
    """读一个 manifest 文件；缺失返回 ([], [])。"""
    p = Path(path)
    if not p.is_file():
        return [], []
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


def apply_removes(entries: list[ManifestEntry], removes: list[str]) -> list[ManifestEntry]:
    """全局移除：凡 name 命中 removes 的条目剔除（最强优先级，跨所有层）。"""
    if not removes:
        return entries
    blacklist = set(removes)
    return [e for e in entries if e.name not in blacklist]


def load_manifest(
    builtin: list[ManifestEntry] | None = None,
    project_dir: str | Path | None = None,
    user_home: str | Path | None = None,
    argv_path: str | Path | None = None,
) -> list[ManifestEntry]:
    """按层叠加载合并（含 remove）：内置 → 项目 → 用户 → argv，最后全局剔除。"""
    from ..config.files import user_config_dir

    entry_layers: list[list[ManifestEntry]] = [builtin or []]
    removes: list[str] = []
    if project_dir is not None:
        e, r = load_manifest_file(Path(project_dir) / ".minidsh" / "manifest.yaml")
        entry_layers.append(e)
        removes.extend(r)
    home = Path(user_home) if user_home else user_config_dir()
    e, r = load_manifest_file(home / "manifest.yaml")
    entry_layers.append(e)
    removes.extend(r)
    if argv_path is not None:
        e, r = load_manifest_file(argv_path)
        entry_layers.append(e)
        removes.extend(r)

    merged = merge_manifests(entry_layers)
    return apply_removes(merged, removes)