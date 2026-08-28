"""base 插件：llm（委托给 minidsh.llm-openai provider 的 apply）。

llm 已三拆：真实 provider 是 capabilities/llm/providers/openai.py（name=minidsh.llm-openai）。
此文件仅作为 base 里「llm」这一激活意图的占位，实际装配走 llm-openai provider。
"""
from __future__ import annotations

from minidsh.capabilities.llm.providers import openai as _openai

name = "minidsh.llm-openai"
inject = ["config"]

# 复用 openai provider 的 apply：provide OpenAILlm 到 ctx.llm
apply = _openai.apply
