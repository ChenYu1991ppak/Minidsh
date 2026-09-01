"""llm 模块：模型层适配 seam（定义 + 消费契约）。

源码对应（ch07）：
- ``LlmRuntime.stream``    ↔ packages/llm/llm/src/index.ts:913（streamWithRegistration :917）
- ``Chunk``               ↔ packages/llm/llm/src/types.ts:291（StreamChunk）

设计（spec §plan）：**接口屏蔽 SDK 类型**。内核与 loop 只认本模块定义的 ``Chunk``
结构与 ``LlmRuntime`` 接口，不 import openai 的任何类型——将来接 anthropic 是
新增一个 provider 模块，不是改内核。

chunk 类型统一为三种（对齐 StreamChunk 协议）。
"""
from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from ...cordis import Service

__all__ = ["Chunk", "LlmRuntime", "estimate_tokens"]


@dataclass(frozen=True)
class Chunk:
    """流式块（StreamChunk 协议，types.ts:291）。

    kind:
    - "text-delta" 文本增量（text 字段）
    - "tool-call"  模型请求一次工具调用（携带 id/name/arguments）
    - "finish"     结束（携带 stop_reason）
    """

    kind: Literal["text-delta", "tool-call", "finish"]
    text: str = ""
    id: str | None = None            # tool-call 用：工具调用 id
    name: str | None = None          # tool-call 用：工具名
    arguments: str | None = None     # tool-call 用：JSON 字符串参数
    stop_reason: str | None = None   # finish 用


class LlmRuntime(Service):
    """LLM 运行时接口。loop 消费此接口，不关心底层 SDK。

    一个 provider（openai / stub / 未来 anthropic）实现此接口。
    与其它能力同机制：子类构造即注册（``super().__init__(ctx, name)``）。
    """

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Chunk]:
        """流式向模型发起一次调用。

        messages：对话消息（`[{"role": "user", "content": ...}, ...]`）。
        tools：工具 schema 列表（OpenAI 兼容格式），None 表示该轮不提供工具。
        产出 Chunk 序列；实现方负责在结束时产出 kind="finish"。
        """


def estimate_tokens(text: str) -> int:
    """token 粗估：chars/4（无 tokenizer 依赖；仅阈值触发用）。

    [教学简化] 真实版用 token-meter 精确计数；此处 chars/4 是行业通用粗估。
    """
    return max(1, len(text) // 4)