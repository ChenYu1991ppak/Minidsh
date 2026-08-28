"""llm-openai provider：OpenAI 兼容接口的流式适配（DeepSeek 官方 API 即此协议）。

源码对应：packages/llm/llm-openai 的流式映射 + ch07 的 assistant/chunk 事件层。

设计（spec §plan 决策 5）：本模块是唯一 import ``openai`` 的地方之一；它把 SDK 的
``ChatCompletionChunk`` 流映射成本仓库统一的 ``Chunk``，内核与 loop 不接触 SDK 类型。
将来加 anthropic = 新写一个 ``llm_anthropic.py``，实现同一 ``LlmRuntime`` 接口。

鉴权与端点由 ``minidsh.config`` 三级链解析后传入（api_key / base_url），
本模块不再自行读环境变量——单一职责：把「给了 key 与端点」这件事交给上层。
"""
from __future__ import annotations

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
                raise RuntimeError(
                    "缺少 API key：设置 MINIDSH_API_KEY（或 DEEPSEEK_API_KEY / OPENAI_API_KEY），"
                    "或用 `minidsh config set api_key <key>` 写入 ~/.minidsh/.credentials.json"
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