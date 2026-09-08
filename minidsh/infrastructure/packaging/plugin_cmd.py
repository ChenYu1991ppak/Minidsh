"""`minidsh plugin` 子命令：add / remove / ls。

对齐官方 ``dsh plugin add/remove``（Python 版）：
- ``add <pkg-spec>``  = pip 安装 + 把该包装的 entry-point ``name`` 追加进用户级 profile
  ``~/.minidsh/profile.yaml``。
- ``remove <name>``    = 从用户 profile 删该 name（不 pip uninstall）。
- ``ls``               = 列出全部 entry-point 发现的插件 + 标注哪些已在用户 profile 激活。

用户级插件激活写 ``~/.minidsh/profile.yaml`` 的 ``plugins:`` 键。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from ..config.files import user_config_dir
from .discover import discover_plugins

__all__ = ["plugin_add", "plugin_remove", "plugin_list"]

USER_PROFILE = user_config_dir() / "profile.yaml"


def _read_user_plugins() -> list[str]:
    """读用户 profile 的 plugins 名列表。"""
    if not USER_PROFILE.is_file():
        return []
    import yaml

    data = yaml.safe_load(USER_PROFILE.read_text(encoding="utf-8")) or {}
    plugins = data.get("plugins") or []
    return [p if isinstance(p, str) else p.get("name") for p in plugins if p]


def _write_user_plugins(names: list[str]) -> None:
    """把插件名列表写成用户 profile.yaml 的 plugins 键（仅 name，无 config）。"""
    USER_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    lines = ["plugins:"]
    for name in names:
        lines.append(f"  - {name}")
    USER_PROFILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plugin_add(pkg_spec: str, *, pip: list[str] | None = None) -> int:
    """安装一个插件包并记入用户 profile。

    ``pip`` 为注入的安装命令前缀（测试用）；缺省 ``[sys.executable, "-m", "pip", "install"]``。
    """
    cmd = pip if pip is not None else [sys.executable, "-m", "pip", "install"]
    result = subprocess.run(cmd + [pkg_spec], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[minidsh] pip 安装失败：{result.stderr.strip()}", file=sys.stderr)
        return 1

    found = discover_plugins()
    existing = set(_read_user_plugins())
    new_names = [n for n in found if n not in existing]
    if new_names:
        _write_user_plugins(_read_user_plugins() + new_names)
        for n in new_names:
            print(f"[minidsh] 已激活插件 {n}")
    else:
        print("[minidsh] 未发现新的 entry-point 插件（检查包的 [project.entry-points.\"minidsh.plugins\"]）")
    return 0


def plugin_remove(name: str) -> int:
    """从用户 profile 移除插件名（不 pip uninstall）。"""
    entries = _read_user_plugins()
    remaining = [n for n in entries if n != name]
    if len(remaining) == len(entries):
        print(f"[minidsh] 插件 {name!r} 不在用户 profile 中", file=sys.stderr)
        return 1
    _write_user_plugins(remaining)
    print(f"[minidsh] 已从用户 profile 移除插件 {name}")
    return 0


def plugin_list() -> int:
    """列出所有 entry-point 发现的插件 + 标注是否已在用户 profile 激活。"""
    active = set(_read_user_plugins())
    found = discover_plugins()
    if not found:
        print("（未发现任何 entry-point 插件）")
        return 0
    for name in sorted(found):
        tag = "已激活" if name in active else "未声明"
        print(f"  {name:<30} {tag}")
    return 0