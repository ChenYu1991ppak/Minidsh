"""配置文件路径与读写。

两个文件：
- ``models.json``  —— 模型配置（对齐 CodeBuddy），每模型内嵌 apiKey，含敏感信息。
- ``settings.json`` —— harness 设置（storage / compaction / tools 白名单），非密。

用户级在 ``~/.minidsh/``（或 ``$MINIDSH_HOME``），项目级在 ``<project>/.minidsh/``。
models.json 因含 apiKey，写盘时 chmod 600。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = [
    "user_models_path",
    "user_settings_path",
    "project_dir",
    "load_json",
    "save_json",
]


def user_config_dir() -> Path:
    """用户级配置根目录：``$MINIDSH_HOME`` 或 ``~/.minidsh``。"""
    home = os.environ.get("MINIDSH_HOME") or Path.home() / ".minidsh"
    return Path(home)


def user_models_path() -> Path:
    """用户级模型配置文件路径。"""
    return user_config_dir() / "models.json"


def user_settings_path() -> Path:
    """用户级 harness 设置文件路径。"""
    return user_config_dir() / "settings.json"


def project_dir(project_root: str | Path) -> Path:
    """项目级配置目录：``<project>/.minidsh/``。"""
    return Path(project_root) / ".minidsh"


def load_json(path: Path) -> dict:
    """读 JSON 文件，缺失或不可解析返回空 dict。"""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path: Path, data: dict, *, secure: bool = False) -> Path:
    """把 dict 写成 JSON。``secure=True`` 时 chmod 600（供含 apiKey 的 models.json）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    if secure:
        os.chmod(tmp, 0o600)
    tmp.replace(path)
    return path