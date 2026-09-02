"""T7 验收测试：llm-openai provider（用 mock client，不发网络）。"""
from __future__ import annotations

import os

import pytest

from minidsh.packages.services.llm import Chunk, OpenAILlm
from minidsh.cordis import Context


class _Fn:
    def __init__(self, name="", arguments=""):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, index, id=None, fn=None):
        self.index = index
        self.id = id
        self.function = fn or _Fn()


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    def __init__(self, delta):
        self.choices = [_Choice(delta)]


class _AsyncStream:
    """可 await、可 async-for 的假流。"""

    def __init__(self, chunks, kwargs_capture=None):
        self._chunks = chunks
        self.kwargs_capture = kwargs_capture

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
        self.kwargs_capture.update(kwargs)
        return _AsyncStream(self._chunks)


class _MockClient:
    def __init__(self, chunks, kwargs_capture):
        self.chat = type("Chat", (), {"completions": _Completions(chunks, kwargs_capture)})


async def _collect(runtime, **kw):
    return [c async for c in runtime.stream([{"role": "user", "content": "hi"}], **kw)]


# ---------- 鉴权 ----------


def test_missing_key_raises():
    # OpenAILlm 缺 api_key（且无 client）时抛错
    with pytest.raises(RuntimeError) as exc:
        OpenAILlm(Context())
    assert "API key" in str(exc.value)


# ---------- 文本流映射 ----------


async def test_text_stream_maps_to_chunks():
    captured = {}
    chunks = [
        _Chunk(_Delta(content="你好")),
        _Chunk(_Delta(content="世界")),
        _Chunk(_Delta(content=None)),
    ]
    llm = OpenAILlm(Context(), client=_MockClient(chunks, captured))

    out = await _collect(llm)
    assert [c.kind for c in out] == ["text-delta", "text-delta", "finish"]
    assert "".join(c.text for c in out if c.kind == "text-delta") == "你好世界"
    assert out[-1].stop_reason == "end-turn"


# ---------- system prompt / tools 透传 ----------


async def test_system_prompt_and_tools_passed_through():
    captured = {}
    llm = OpenAILlm(Context(), client=_MockClient([_Chunk(_Delta(content="x"))], captured))

    await _collect(llm, system_prompt="SYS", tools=[{"type": "function"}])

    assert captured["messages"][0] == {"role": "system", "content": "SYS"}
    assert captured["tools"] == [{"type": "function"}]
    assert captured["stream"] is True
    assert captured["model"] == "deepseek-chat"


# ---------- 工具调用聚合 ----------


async def test_tool_call_aggregation_across_deltas():
    captured = {}
    chunks = [
        _Chunk(_Delta(tool_calls=[_ToolCall(0, id="call-1", fn=_Fn(name="bash"))])),
        _Chunk(_Delta(tool_calls=[_ToolCall(0, fn=_Fn(arguments='{"cm'))])),
        _Chunk(_Delta(tool_calls=[_ToolCall(0, fn=_Fn(arguments='d":"ls"}'))])),
    ]
    llm = OpenAILlm(Context(), client=_MockClient(chunks, captured))

    out = await _collect(llm, tools=[{}])
    assert [c.kind for c in out] == ["tool-call", "finish"]
    tc = out[0]
    assert tc.id == "call-1"
    assert tc.name == "bash"
    assert tc.arguments == '{"cmd":"ls"}'  # 分片拼接
    assert out[-1].stop_reason == "tool-use"


async def test_multiple_tool_calls_ordered_by_index():
    captured = {}
    chunks = [
        _Chunk(_Delta(tool_calls=[_ToolCall(1, id="b", fn=_Fn(name="second"))])),
        _Chunk(_Delta(tool_calls=[_ToolCall(0, id="a", fn=_Fn(name="first"))])),
    ]
    llm = OpenAILlm(Context(), client=_MockClient(chunks, captured))

    out = await _collect(llm, tools=[{}])
    calls = [c for c in out if c.kind == "tool-call"]
    assert [c.name for c in calls] == ["first", "second"]  # 按 index 升序
    assert [c.id for c in calls] == ["a", "b"]