"""prompt 能力：system-prompt 分节注册 / 组装 / 渲染。

单一实现（无多 provider），故无 ``providers/``——呼应官方「不要预防性拆分」。
消费方（tools / skills / workspace 的 AGENTS.md）各自注册自己的节，loop 在
每次调用前 assemble + render。
"""
from __future__ import annotations

from .definition import SystemPromptService, PromptSection, PromptAssembly, render_prompt

__all__ = ['SystemPromptService', 'PromptSection', 'PromptAssembly', 'render_prompt']
