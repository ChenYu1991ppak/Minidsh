"""minidsh 内置 base 插件包：把 harness 能力模块化为「具名插件」。

每个插件是 module 形态（模块级 name/inject/apply），由内置 base 清单声明激活。
base 插件需要项目级配置（root/cfg/llm_client），故用工厂函数按配置生成；第三方
插件（纯 module）走 entry-point 直发现。
"""
from __future__ import annotations

from .plugins import build_base_plugins, base_manifest

__all__ = ["build_base_plugins", "base_manifest"]