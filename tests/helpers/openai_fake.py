"""测试用 openai 假 client：回放固定的 chunk 流，无真实网络、无 SDK 依赖。

用途：确定性驱动 llm-openai provider 的流式映射、以及完整 loop 的集成/e2e 测试。
它模拟的是 ``AsyncOpenAI`` 的最小可迭代接口，不是 LLM 实现——回应「测试走 openai mock」
而非「在源码里保留一个伪 LLM」。

用法：``make_client(chunks)`` 返回一个带 ``chat.completions.create`` 异步方法的假 client，
``create`` 返回可 await、可 async-for 的流。
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "make_client",
    "make_scripted_client",
    "text_chunks",
    "tool_chunks",
    "TextChunk",
    "ReasoningChunk",
    "ToolChunk",
    "chunks_text",
]


class _Fn:
    __slots__ = ("name", "arguments")

    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    __slots__ = ("index", "id", "function")

    def __init__(self, index, id=None, fn=None):
        self.index = index
        self.id = id
        self.function = fn or _Fn()


class _Delta:
    __slots__ = ("content", "tool_calls", "reasoning_content")

    def __init__(self, content=None, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content


class _Choice:
    __slots__ = ("delta",)

    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    __slots__ = ("choices",)

    def __init__(self, delta):
        self.choices = [_Choice(delta)]


class _AsyncStream:
    """可 await（返回自身）、可 async-for 的假流。"""

    def __init__(self, chunks, kwargs_capture=None):
        self._chunks = chunks
        self.kwargs_capture = kwargs_capture

    def __await__(self):
        async def _resolve():
            return self

        return _resolve().__await__()

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Completions:
    def __init__(self, chunks, kwargs_capture):
        self._chunks = chunks
        self.kwargs_capture = kwargs_capture

    async def create(self, **kwargs):
        if self.kwargs_capture is not None:
            self.kwargs_capture.update(kwargs)
        return _AsyncStream(self._chunks)


class _Chat:
    def __init__(self, chunks, kwargs_capture):
        self.completions = _Completions(chunks, kwargs_capture)


class _FakeClient:
    def __init__(self, chunks, kwargs_capture=None):
        self.chat = _Chat(chunks, kwargs_capture)


def make_client(chunks, kwargs_capture: dict | None = None):
    """构造假 client；``kwargs_capture`` 用于断言 provider 透传的请求参数。"""
    return _FakeClient(chunks, kwargs_capture)


# ---------------------------------------------------------------------------
# 常用 chunk 构造器
# ---------------------------------------------------------------------------


def TextChunk(content: str) -> _Chunk:
    """一个文本增量 chunk。"""
    return _Chunk(_Delta(content=content))


def ReasoningChunk(reasoning: str) -> _Chunk:
    """一个思考文本增量 chunk（reasoning_content）。"""
    return _Chunk(_Delta(reasoning_content=reasoning))


def ToolChunk(index: int, id=None, name="", arguments=""):
    """一个工具调用增量 chunk（name/arguments 可跨 chunk 分片）。"""
    return _Chunk(_Delta(tool_calls=[_ToolCall(index, id=id, fn=_Fn(name=name, arguments=arguments))]))


def text_chunks(*pieces: str, capture=None):
    """一段纯文本流：多块文本增量。返回 (fake_client, kwargs_capture)。"""
    capture = {} if capture is None else capture
    return make_client([TextChunk(p) for p in pieces], capture)


def tool_chunks(pieces: list[tuple[int, str | None, str, str]], capture=None):
    """一段工具调用流：pieces = [(index, id, name, arguments), ...]（按流式到达顺序）。"""
    capture = {} if capture is None else capture
    chunks = [ToolChunk(idx, id=tid, name=name, arguments=args) for (idx, tid, name, args) in pieces]
    return make_client(chunks, capture)


def make_scripted_client(script: list[dict], capture=None):
    """按「轮次」回放剧本的假 client。

    script[i] 可以是：
    - ``{"text": "..."}`` → 该轮产文本增量 + finish(end-turn)
    - ``{"reasoning": "...", "text": "..."}`` → 先思考增量，再回复文本增量 + finish(end-turn)
    - ``{"tool_calls": [(name, arguments, id), ...]}`` → 该轮产工具调用 + finish(tool-use)

    每轮消耗一行剧本；用尽后所有轮次回放最后一行，否则回放 ``{"text": ""}``。
    返回一个薄对象，供测试封装为 ``OpenAILlm(client=...)``。
    """
    calls = {"n": 0}

    def chunks_for(_messages, _system, _tools):
        idx = min(calls["n"], len(script) - 1) if script else 0
        calls["n"] += 1
        row = script[idx] if script else {"text": ""}
        if "tool_calls" in row:
            pieces = []
            for j, (name, arguments, tid) in enumerate(row["tool_calls"]):
                pieces.append(ToolChunk(j, id=tid or f"call-{j}", name=name, arguments=arguments))
            return pieces
        pieces = []
        if row.get("reasoning"):
            pieces.append(ReasoningChunk(row["reasoning"]))
        pieces.append(TextChunk(row.get("text", "")))
        return pieces

    return _ScriptedClient(chunks_for)


def chunks_text(chunks: list) -> str:
    """把一组 TextChunk 的文本拼起来（测试断言便利函数）。"""
    return "".join(c.choices[0].delta.content or "" for c in chunks)


class _ScriptedClient:
    """按轮次回放剧本的假 client，暴露与 OpenAILlm 兼容的 chat.completions.create。"""

    def __init__(self, chunk_provider):
        self._chunk_provider = chunk_provider
        self.chat = _ScriptedChat(chunk_provider)


class _ScriptedChat:
    def __init__(self, chunk_provider):
        self.completions = _ScriptedCompletions(chunk_provider)


class _ScriptedCompletions:
    def __init__(self, chunk_provider):
        self._chunk_provider = chunk_provider

    async def create(self, **kwargs):
        chunks = self._chunk_provider(kwargs.get("messages"), kwargs.get("system_prompt"), kwargs.get("tools"))
        return _AsyncStream(chunks)