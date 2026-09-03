"""llm-openai provider：OpenAI 兼容接口的流式适配（DeepSeek 官方 API 即此协议）。

源码对应：packages/llm/llm-openai 的流式映射 + ch07 的 assistant/chunk 事件层。

三角色的「提供方」：模块级 ``name/inject/apply`` 的插件，``apply`` 里
``ctx.provide("llm", OpenAILlm(...))``。配置经 ``inject=["config"]`` 读 ``ctx.config``，
不读环境变量——本模块是唯一 import openai 的地方，把 SDK 的 ``ChatCompletionChunk``
流映射成本仓库统一的 ``Chunk``，内核与 loop 不接触 SDK 类型。

思考/强度：经 ``..softmap`` 软映射层（按 model id 家族）决定 reasoning_effort /
thinking / enable_thinking / temperature 剥离；reasoning_content 流式产
``reasoning-delta`` chunk。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..definition import Chunk, LlmRuntime
from .. import softmap
from minidsh.cordis import CapabilityProvider

__all__ = ["OpenAILlm"]

name = "minidsh.llm-openai"
inject = ["config"]


class OpenAILlm(LlmRuntime, CapabilityProvider):
    """OpenAI 兼容的流式 LLM。构造即注册（``ctx.llm``）。"""

    def __init__(
        self,
        ctx,
        *,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        reasoning_effort: str = "medium",
        client: Any | None = None,
    ):
        super().__init__(ctx)
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort
        self._client = client
        if client is None:
            from openai import AsyncOpenAI

            if not api_key:
                raise RuntimeError(
                    "缺少 API key：请在 models.json 里为该模型填写 apiKey 字段"
                )
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def reconfigure(self, spec) -> None:
        """运行时更新模型/温度/思考强度/url/key（TUI 切模型或强度用）。"""
        self.model = spec.id
        self.api_key = spec.api_key or self.api_key
        self.base_url = spec.url or self.base_url
        self.temperature = spec.temperature
        self.reasoning_effort = spec.reasoning_effort
        # 换 base 端点/apiKey 时重建底层 client
        if spec.url or spec.api_key:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def _request_kwargs(self, tools) -> dict[str, Any]:
        """按当前 model 组装请求 kwargs（含软映射层的思考/温度参数）。"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "stream": True,
        }
        # temperature：reasoning 模型剥离，否则透传
        if self.temperature is not None and not softmap.strip_tuning(self.model):
            kwargs["temperature"] = self.temperature
        # reasoning_effort：软映射
        effort = softmap.reasoning_effort_map(self.model, self.reasoning_effort)
        if effort is not None:
            kwargs["reasoning_effort"] = effort
        # thinking / enable_thinking：软映射（DeepSeek/Kimi/Qwen 开关）
        optin = softmap.thinking_optin(self.model, self.reasoning_effort)
        if optin is not None:
            # OpenAI SDK 需要 extra_body 传非标准字段
            kwargs["extra_body"] = optin
        if tools:
            kwargs["tools"] = tools
        return kwargs

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

        kwargs = self._request_kwargs(tools)
        kwargs["messages"] = payload

        stream = await self._client.chat.completions.create(**kwargs)

        # 工具调用按 index 聚合（流式里 name/arguments 会分片到达）
        tool_calls: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield Chunk(kind="reasoning-delta", reasoning=reasoning)
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


def apply(ctx):
    """构造 OpenAILlm（自注册 ctx.llm），配置读 ctx.config（当前模型）。"""
    cfg = ctx.config
    model = cfg.current
    if model is None:
        raise RuntimeError(
            "未配置可用模型：请在 models.json 的 models[] 里至少提供一个模型，"
            "并用 currentModel 或 availableModels 指定当前模型"
        )
    if not model.url:
        raise RuntimeError(
            f"模型 {model.id!r} 未配置 url（OpenAI 兼容 base_url）：该模型不可用。"
            "请在 models.json 里为该模型填写 url 字段。"
        )
    OpenAILlm(
        ctx,
        model=model.id,
        api_key=model.api_key or None,
        base_url=model.url,
        temperature=model.temperature,
        reasoning_effort=model.reasoning_effort,
    )