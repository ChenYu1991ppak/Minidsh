"""M5 验收测试：lsp（LspService 注册表/选择 + NoopLspProvider + tool-lsp）。

- register_provider 原子校验 + 冲突拒绝 + disposer。
- query 按扩展名选 provider 并转发（带 languageId）。
- NoopLspProvider 四操作空结果（非错误），available=False。
- tool-lsp：1-based → 零基转换 + 调 ctx.lsp.query + 无 provider 降级。
"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from minidsh.packages.services.lsp import (
    LspService,
    LspError,
    LspProvider,
    LspQueryRequest,
    LspProviderQuery,
    LspPosition,
    LspQueryResult,
    LspLocation,
    LspRange,
    final_extension,
)
from minidsh.packages.services.lsp.providers.noop import NoopLspProvider


# ---------------------------------------------------------------------------
# final_extension
# ---------------------------------------------------------------------------


def test_final_extension_basic():
    assert final_extension("foo.py") == ".py"
    assert final_extension("Foo.TS") == ".ts"
    assert final_extension("a/b/c.go") == ".go"
    assert final_extension("a\\b\\c.rs") == ".rs"
    assert final_extension("foo.d.ts") == ".ts"


def test_final_extension_none():
    assert final_extension("Makefile") == ""
    assert final_extension(".bashrc") == ""     # 前导点 dotfile
    assert final_extension("a/b/file") == ""


# ---------------------------------------------------------------------------
# 测试 provider
# ---------------------------------------------------------------------------


class _RecordingProvider(LspProvider):
    id = "rec"
    extensionToLanguage = {".py": "python"}

    def __init__(self, result=None):
        self.queries = []
        self._result = result or LspQueryResult(kind="locations", locations=[])

    async def query(self, request: LspProviderQuery) -> LspQueryResult:
        self.queries.append(request)
        return self._result


# ---------------------------------------------------------------------------
# LspService：注册校验 + 冲突
# ---------------------------------------------------------------------------


def test_register_rejects_empty_id():
    ctx = Context()
    lsp = LspService(ctx)

    class _P(LspProvider):
        id = ""
        extensionToLanguage = {".py": "python"}

    with pytest.raises(LspError) as ei:
        lsp.register_provider(_P())
    assert ei.value.code == "LSP_INVALID_PROVIDER"


def test_register_rejects_no_extensions():
    ctx = Context()
    lsp = LspService(ctx)

    class _P(LspProvider):
        id = "p"
        extensionToLanguage = {}

    with pytest.raises(LspError) as ei:
        lsp.register_provider(_P())
    assert ei.value.code == "LSP_INVALID_PROVIDER"


def test_register_rejects_duplicate_id():
    ctx = Context()
    lsp = LspService(ctx)
    lsp.register_provider(_RecordingProvider())

    class _P(LspProvider):
        id = "rec"
        extensionToLanguage = {".go": "go"}

    with pytest.raises(LspError) as ei:
        lsp.register_provider(_P())
    assert ei.value.code == "LSP_CONFLICT"


def test_register_rejects_extension_conflict():
    ctx = Context()
    lsp = LspService(ctx)
    lsp.register_provider(_RecordingProvider())  # 占 .py

    class _P(LspProvider):
        id = "other"
        extensionToLanguage = {".py": "python3"}

    with pytest.raises(LspError) as ei:
        lsp.register_provider(_P())
    assert ei.value.code == "LSP_CONFLICT"


def test_register_disposer_releases():
    ctx = Context()
    lsp = LspService(ctx)
    dispose = lsp.register_provider(_RecordingProvider())
    assert ".py" in lsp._routes
    dispose()
    assert ".py" not in lsp._routes
    assert "rec" not in lsp._provider_ids


# ---------------------------------------------------------------------------
# LspService：query 选择 + 转发
# ---------------------------------------------------------------------------


async def test_query_selects_by_extension_and_forwards():
    ctx = Context()
    lsp = LspService(ctx)
    provider = _RecordingProvider()
    lsp.register_provider(provider)

    req = LspQueryRequest(operation="goToDefinition", filePath="a/b.py",
                          position=LspPosition(line=1, character=2))
    result = await lsp.query(req)
    assert result.kind == "locations"
    # 转发的请求带上推导的 languageId
    assert provider.queries[0].languageId == "python"
    assert provider.queries[0].filePath == "a/b.py"


async def test_query_unmatched_extension_unavailable():
    ctx = Context()
    lsp = LspService(ctx)
    lsp.register_provider(_RecordingProvider())
    req = LspQueryRequest(operation="hover", filePath="foo.zzz",
                          position=LspPosition(line=0, character=0))
    with pytest.raises(LspError) as ei:
        await lsp.query(req)
    assert ei.value.code == "LSP_UNAVAILABLE"


async def test_query_returns_provider_result():
    ctx = Context()
    lsp = LspService(ctx)
    loc = LspLocation(uri="file:///x.py", range=LspRange(
        start=LspPosition(line=0, character=0), end=LspPosition(line=0, character=3)))
    lsp.register_provider(_RecordingProvider(LspQueryResult(kind="locations", locations=[loc])))
    req = LspQueryRequest(operation="findReferences", filePath="x.py",
                          position=LspPosition(line=0, character=0))
    result = await lsp.query(req)
    assert len(result.locations) == 1
    assert result.locations[0].uri == "file:///x.py"


# ---------------------------------------------------------------------------
# NoopLspProvider
# ---------------------------------------------------------------------------


async def test_noop_provider_returns_empty_locations():
    noop = NoopLspProvider()
    req = LspProviderQuery(operation="goToDefinition", filePath="f.py",
                           position=LspPosition(line=0, character=0), languageId="python")
    result = await noop.query(req)
    assert result.kind == "locations"
    assert result.locations == []


async def test_noop_provider_returns_null_hover():
    noop = NoopLspProvider()
    req = LspProviderQuery(operation="hover", filePath="f.py",
                           position=LspPosition(line=0, character=0), languageId="python")
    result = await noop.query(req)
    assert result.kind == "hover"
    assert result.hover is None


def test_noop_provider_available_false():
    noop = NoopLspProvider()
    assert noop.available() is False


async def test_noop_provider_registered_in_runtime():
    """runtime 插件把 noop 注册进 ctx.lsp，query 返回空（非错误）。"""
    from minidsh.packages.services.lsp.providers import runtime as lsp_runtime
    ctx = Context()
    lsp_runtime.apply(ctx)
    req = LspQueryRequest(operation="goToDefinition", filePath="f.py",
                          position=LspPosition(line=0, character=0))
    result = await ctx.lsp.query(req)
    assert result.locations == []


# ---------------------------------------------------------------------------
# tool-lsp
# ---------------------------------------------------------------------------


def _tool_ctx():
    ctx = Context()
    ctx.provide("config", Config())
    ToolRuntime(ctx)
    LspService(ctx)
    from minidsh.packages.tools import lsp as tool_lsp
    tool_lsp.apply(ctx)
    return ctx


async def test_tool_lsp_registered_with_schema():
    ctx = _tool_ctx()
    tool = ctx.tools.get("lsp")
    assert tool is not None
    params = tool.parameters
    for field in ("filePath", "operation", "line", "character"):
        assert field in params["properties"]
    assert set(params["required"]) == {"filePath", "operation", "line", "character"}


async def test_tool_lsp_converts_1based_to_0based():
    ctx = _tool_ctx()
    provider = _RecordingProvider()
    ctx.lsp.register_provider(provider)
    execute = ctx.tools.get("lsp").execute
    value = await execute({"filePath": "a.py", "operation": "goToDefinition",
                           "line": 5, "character": 3})
    assert value["available"] is True
    # 1-based (5,3) → 零基 (4,2)
    assert provider.queries[0].position.line == 4
    assert provider.queries[0].position.character == 2


async def test_tool_lsp_rejects_invalid_operation():
    ctx = _tool_ctx()
    execute = ctx.tools.get("lsp").execute
    with pytest.raises(ValueError):
        await execute({"filePath": "a.py", "operation": "bogus", "line": 1, "character": 1})


async def test_tool_lsp_no_provider_degrades():
    ctx = _tool_ctx()
    execute = ctx.tools.get("lsp").execute
    value = await execute({"filePath": "a.unknownext", "operation": "hover",
                           "line": 1, "character": 1})
    assert value["available"] is False
    assert value["code"] == "LSP_UNAVAILABLE"


async def test_tool_lsp_hover_result():
    ctx = _tool_ctx()
    from minidsh.packages.services.lsp import LspHover

    class _HoverProvider(LspProvider):
        id = "hp"
        extensionToLanguage = {".py": "python"}

        async def query(self, request):
            return LspQueryResult(kind="hover", hover=LspHover(contents="def foo()"))

    ctx.lsp.register_provider(_HoverProvider())
    execute = ctx.tools.get("lsp").execute
    value = await execute({"filePath": "a.py", "operation": "hover", "line": 1, "character": 1})
    assert value["available"] is True
    assert value["kind"] == "hover"
    assert value["hover"]["contents"] == "def foo()"


async def test_tool_lsp_execute_via_runtime():
    """经 ToolRuntime.execute 全链路调 lsp。"""
    ctx = _tool_ctx()
    result = await ctx.tools.execute(ToolExecution(
        call_id="c1", name="lsp",
        arguments={"filePath": "a.unknownext", "operation": "hover", "line": 1, "character": 1}))
    assert result.is_error is False
    assert "unavailable" in result.content


# ---------------------------------------------------------------------------
# 纯函数：解析 / 值转换 / 渲染（覆盖分支）
# ---------------------------------------------------------------------------


def test_parse_args_rejects_empty_filepath():
    from minidsh.packages.tools.lsp import _parse_args
    with pytest.raises(ValueError):
        _parse_args({"filePath": "  ", "operation": "hover", "line": 1, "character": 1})


def test_parse_args_rejects_bad_line():
    from minidsh.packages.tools.lsp import _parse_args
    with pytest.raises(ValueError):
        _parse_args({"filePath": "a.py", "operation": "hover", "line": 0, "character": 1})


def test_parse_args_rejects_bad_character():
    from minidsh.packages.tools.lsp import _parse_args
    with pytest.raises(ValueError):
        _parse_args({"filePath": "a.py", "operation": "hover", "line": 1, "character": 0})


def test_result_to_value_locations_with_range():
    from minidsh.packages.tools.lsp import _result_to_value
    loc = LspLocation(uri="file:///x.py", range=LspRange(
        start=LspPosition(line=2, character=4), end=LspPosition(line=2, character=9)))
    value = _result_to_value(LspQueryResult(kind="locations", locations=[loc]))
    assert value["kind"] == "locations"
    assert value["locations"][0]["range"]["start"]["line"] == 2
    assert value["locations"][0]["range"]["end"]["character"] == 9


def test_result_to_value_hover_none():
    from minidsh.packages.tools.lsp import _result_to_value
    value = _result_to_value(LspQueryResult(kind="hover", hover=None))
    assert value["kind"] == "hover"
    assert value["hover"] is None


def test_render_locations_with_position():
    from minidsh.packages.tools.lsp import _render
    value = {"available": True, "kind": "locations", "locations": [
        {"uri": "file:///x.py", "range": {"start": {"line": 4, "character": 2},
                                          "end": {"line": 4, "character": 5}}}]}
    out = _render({}, value)
    # 零基 (4,2) → 展示为 1-based 5:3
    assert "file:///x.py:5:3" in out


def test_render_locations_empty():
    from minidsh.packages.tools.lsp import _render
    out = _render({}, {"available": True, "kind": "locations", "locations": []})
    assert out == "No locations found."


def test_render_hover_contents():
    from minidsh.packages.tools.lsp import _render
    out = _render({}, {"available": True, "kind": "hover", "hover": {"contents": "sig"}})
    assert out == "sig"


def test_render_hover_none():
    from minidsh.packages.tools.lsp import _render
    out = _render({}, {"available": True, "kind": "hover", "hover": None})
    assert out == "No hover information."


def test_render_unavailable():
    from minidsh.packages.tools.lsp import _render
    out = _render({}, {"available": False, "error": "boom"})
    assert "unavailable" in out
    assert "boom" in out


async def test_tool_lsp_locations_with_range_via_runtime():
    """全链路：provider 返回带 range 的 location，渲染含 1-based 位置。"""
    ctx = _tool_ctx()

    class _LocProvider(LspProvider):
        id = "lp"
        extensionToLanguage = {".py": "python"}

        async def query(self, request):
            return LspQueryResult(kind="locations", locations=[LspLocation(
                uri="file:///def.py",
                range=LspRange(start=LspPosition(line=9, character=0),
                               end=LspPosition(line=9, character=3)))])

    ctx.lsp.register_provider(_LocProvider())
    result = await ctx.tools.execute(ToolExecution(
        call_id="c", name="lsp",
        arguments={"filePath": "a.py", "operation": "goToDefinition", "line": 1, "character": 1}))
    assert result.is_error is False
    # 零基 line 9 → 1-based 10
    assert "file:///def.py:10:1" in result.content
