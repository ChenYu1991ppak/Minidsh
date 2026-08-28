"""config 模块：模型配置（models.json）+ harness 设置（settings.json）。

对齐 CodeBuddy 的 models.json 结构（每模型内嵌 apiKey）+ 独立的 settings.json。
优先级：项目级 `<project>/.minidsh/` 覆盖用户级 `~/.minidsh/`（模型拼接、settings 覆盖）。
无 provider 抽象，当前模型由 currentModel / availableModels 定位。
"""
from __future__ import annotations

from .config import Config, ModelSpec
from .resolve import resolve_config
from .files import (
    user_models_path,
    user_settings_path,
    project_dir,
    load_json,
    save_json,
)

__all__ = [
    "Config",
    "ModelSpec",
    "resolve_config",
    "user_models_path",
    "user_settings_path",
    "project_dir",
    "load_json",
    "save_json",
]