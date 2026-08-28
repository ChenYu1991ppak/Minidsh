"""`minidsh plugin` 子命令：add / remove / ls。

对齐官方 ``dsh plugin add/remove``（Python 版）：
- ``add <pkg-spec>``  = pip 安装 + 把该包装的 entry-point ``name`` 追加进用户级
  ``~/.minidsh/manifest.yaml``。
- ``remove <name>``    = 从 manifest 删该 name（不 pip uninstall，见 SPEC-packaging §9）。
- ``ls``               = 列出全部 entry-point 发现的插件 + 标注哪些已在 manifest 激活。

manifest 读写走 ``minidsh.manifest.schema``（parse/load）；用户级路径复用 config.files。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..config.files import user_config_dir
from ..manifest import load_manifest_file, ManifestEntry
from .discover import discover_plugins

__all__ = ["plugin_add", "plugin_remove", "plugin_list"]

USER_MANIFEST = user_config_dir() / "manifest.yaml"


def _read_user_manifest() -> list[ManifestEntry]:
    entries, _removes = load_manifest_file(USER_MANIFEST)
    return entries


def _write_user_manifest(entries: list[str]) -> None:
    """把「插件名列表」写成用户级 manifest.yaml（仅 name，无 config）。"""
    USER_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    lines = ["plugins:"]
    for name in entries:
        lines.append(f"  - {name}")
    USER_MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plugin_add(pkg_spec: str, *, pip: list[str] | None = None) -> int:
    """安装一个插件包并记入用户 manifest。

    ``pip`` 为注入的安装命令前缀（测试用）；缺省 ``[sys.executable, "-m", "pip", "install"]``。
    """
    cmd = pip if pip is not None else [sys.executable, "-m", "pip", "install"]
    result = subprocess.run(cmd + [pkg_spec], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[minidsh] pip 安装失败：{result.stderr.strip()}", file=sys.stderr)
        return 1

    # 发现该 pkg 声明的插件名（entry-point name 即插件名）
    found = discover_plugins()
    existing = {e.name for e in _read_user_manifest()}
    # 无法精确定位「刚装的这个包贡献了哪些插件」，v1 保守：把新出现的插件名一并记入
    new_names = [n for n in found if n not in existing]
    if new_names:
        _write_user_manifest([e.name for e in _read_user_manifest()] + new_names)
        for n in new_names:
            print(f"[minidsh] 已激活插件 {n}")
    else:
        print("[minidsh] 未发现新的 entry-point 插件（检查包的 [project.entry-points.\"minidsh.plugins\"]）")
    return 0


def plugin_remove(name: str) -> int:
    """从用户 manifest 移除插件名（不 pip uninstall）。"""
    entries = _read_user_manifest()
    remaining = [e.name for e in entries if e.name != name]
    if len(remaining) == len(entries):
        print(f"[minidsh] 插件 {name!r} 不在 manifest 中", file=sys.stderr)
        return 1
    _write_user_manifest(remaining)
    print(f"[minidsh] 已从 manifest 移除插件 {name}")
    return 0


def plugin_list() -> int:
    """列出所有 entry-point 发现的插件 + 标注是否已激活（在 manifest 中）。"""
    active = {e.name for e in _read_user_manifest()}
    found = discover_plugins()
    if not found:
        print("（未发现任何 entry-point 插件）")
        return 0
    for name in sorted(found):
        tag = "已激活" if name in active else "未声明"
        print(f"  {name:<30} {tag}")
    return 0