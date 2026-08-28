"""llm-openai provider：OpenAI 兼容接口的流式适配（DeepSeek 官方 API 即此协议）。

源码对应：packages/llm/llm-openai 的流式映射 + ch07 的 assistant/chunk 事件层。

设计（spec §plan 决策 5）：本模块是唯一 import ``openai`` 的地方之一；它把 SDK 的
``ChatCompletionChunk`` 流映射成本仓库统一的 ``Chunk``，内核与 loop 不接触 SDK 类型。
将来加 anthropic = 新写一个 ``llm_anthropic.py``，实现同一 ``LlmRuntime`` 接口。

鉴权：``DEEPSEEK_API_KEY`` 优先，其次是 ``OPENAI_API_KEY``。
端点：``DEEPSEEK_BASE_URL`` / ``OPENAI_BASE_URL`` 可覆盖（默认 DeepSeek 端点）。
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from .seam import Chunk, LlmRuntime

__all__ = ["OpenAILlm"]


class OpenAILlm(LlmRuntime):
    """OpenAI 兼容的流式 LLM。可注入 client 便于测试（mock）。"""

    def __init__(
        self,
        *,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ):
        if client is not None:
            self._client = client
        else:
            from openai import AsyncOpenAI

            api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get(
                "OPENAI_API_KEY"
            )
            if not api_key:
                raise RuntimeError(
                    "缺少 API key：请设置 DEEPSEEK_API_KEY（或 OPENAI_API_KEY）"
                )
            base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get(
                "OPENAI_BASE_URL"
            )
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str = "",
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Chunk]:
        payload: list[dict[str, Any]] = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        payload.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self._client.chat.completions.create(**kwargs)

        # 工具调用按 index 聚合（流式里 name/arguments 会分片到达）
        tool_calls: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                yield Chunk(kind="text-delta", text=delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(
                        tc.index,
                        {"id": tc.id or "", "name": "", "arguments": ""},
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments

        # 结束：工具调用优先；否则文本结束
        if tool_calls:
            # 按 index 顺序产出 tool-call chunk
            for idx in sorted(tool_calls):
                call = tool_calls[idx]
                yield Chunk(
                    kind="tool-call",
                    id=call["id"] or f"call-{idx}",
                    name=call["name"],
                    arguments=call["arguments"] or "{}",
                )
            yield Chunk(kind="finish", stop_reason="tool-use")
        else:
            yield Chunk(kind="finish", stop_reason="end-turn")