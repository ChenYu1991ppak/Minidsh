"""llm 能力：模型层适配 seam（定义 + OpenAI provider）。

三角色：``definition.py`` 是定义（LlmRuntime + Chunk），``providers/openai.py``
是 provider（唯一 import openai 的地方），consumer 是 applications/loop。
接口屏蔽 SDK 类型——将来加 anthropic = 新增一个 providers/ 实现，loop 不动。

``softmap.py`` 是按 model id 家族的软映射层（思考强度/推理模型差异收敛）。
"""
from __future__ import annotations

from .definition import Chunk, LlmRuntime, estimate_tokens
from .providers.openai import OpenAILlm
from . import softmap

__all__ = ["Chunk", "LlmRuntime", "OpenAILlm", "estimate_tokens", "softmap"]
