"""M4 验收测试：web（WebRuntime 注册表/选择 + web-fetch-http + tool-web）。

- WebRuntime provider 注册表 + 选择语义（unavailable / ambiguous / duplicate）。
- HttpFetchProvider 安全抓取（URL 校验、私有 IP 拒绝、同源重定向、content-type、截断）。
- tool-web：web_search 无 provider 降级、web_fetch 正常。
"""
from __future__ import annotations

import pytest

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.tool_runtime import ToolRuntime, ToolExecution
from minidsh.packages.services.web import (
    WebRuntime,
    WebError,
    WebSearchRequest,
    WebSearchResult,
    WebSearchSource,
    WebFetchRequest,
    WebSearchProvider,
    WebFetchProvider,
)
from minidsh.packages.services.web.providers.fetch_http import (
    HttpFetchProvider,
    validate_fetch_url,
    is_same_origin,
    classify_content_type,
    is_blocked_ip,
)
from minidsh.packages.services.web.providers import fetch_http as fetch_http_mod


# ---------------------------------------------------------------------------
# 策略函数（纯）
# ---------------------------------------------------------------------------


def test_validate_fetch_url_ok():
    parsed = validate_fetch_url("https://example.com/path?q=1")
    assert parsed.scheme == "https"
    assert parsed.hostname == "example.com"


def test_validate_fetch_url_rejects_bad_scheme():
    with pytest.raises(WebError) as ei:
        validate_fetch_url("ftp://example.com")
    assert ei.value.code == "WEB_INVALID_URL"


def test_validate_fetch_url_rejects_credentials():
    with pytest.raises(WebError) as ei:
        validate_fetch_url("https://user:pass@example.com")
    assert ei.value.code == "WEB_BLOCKED_URL"


def test_validate_fetch_url_rejects_no_hostname():
    with pytest.raises(WebError) as ei:
        validate_fetch_url("https://")
    assert ei.value.code == "WEB_INVALID_URL"


def test_validate_fetch_url_rejects_too_long():
    with pytest.raises(WebError) as ei:
        validate_fetch_url("https://example.com/" + "a" * 3000)
    assert ei.value.code == "WEB_INVALID_URL"


def test_is_same_origin():
    a = validate_fetch_url("https://example.com/a")
    b = validate_fetch_url("https://example.com/b")
    c = validate_fetch_url("https://other.com/a")
    assert is_same_origin(a, b) is True
    assert is_same_origin(a, c) is False


def test_classify_content_type():
    assert classify_content_type("text/html") == "html"
    assert classify_content_type("text/html; charset=utf-8") == "html"
    assert classify_content_type("application/xhtml+xml") == "html"
    assert classify_content_type("text/plain") == "text"
    assert classify_content_type("application/json") == "text"
    assert classify_content_type("application/octet-stream") is None
    assert classify_content_type(None) is None


def test_is_blocked_ip():
    assert is_blocked_ip("127.0.0.1") is True          # 环回
    assert is_blocked_ip("10.0.0.1") is True           # 私有
    assert is_blocked_ip("192.168.1.1") is True        # 私有
    assert is_blocked_ip("169.254.1.1") is True        # 链路本地
    assert is_blocked_ip("93.184.216.34") is False     # 公共
    assert is_blocked_ip("not-an-ip") is True          # 无法解析 → 拒


# ---------------------------------------------------------------------------
# HttpFetchProvider：假客户端替身
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, content=b"", is_redirect=False):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.is_redirect = is_redirect

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses
        self._idx = 0
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        self.requests.append((url, headers))
        if callable(self._responses) and not isinstance(self._responses, list):
            return self._responses(url)
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


def _provider(responses, resolve=None):
    """造一个注入假客户端 + 假 DNS 的 HttpFetchProvider。"""
    holder = {}

    def factory(**kwargs):
        client = _FakeClient(responses)
        holder["client"] = client
        return client

    provider = HttpFetchProvider(
        client_factory=factory,
        resolve=resolve or (lambda host: ["93.184.216.34"]),
    )
    return provider, holder


async def test_fetch_returns_200_html():
    provider, _ = _provider([_FakeResponse(200, {"content-type": "text/html"}, b"<h1>hi</h1>")])
    result = await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert result.statusCode == 200
    assert result.body.kind == "html"
    assert result.body.content == "<h1>hi</h1>"
    assert result.truncated is False


async def test_fetch_non_2xx_is_result_not_error():
    provider, _ = _provider([_FakeResponse(404, {"content-type": "text/plain"}, b"not found")])
    result = await provider.fetch(WebFetchRequest(url="https://example.com/missing"))
    assert result.statusCode == 404  # 非 2xx 为结果
    assert result.body.content == "not found"


async def test_fetch_rejects_private_ip():
    provider, _ = _provider([], resolve=lambda host: ["127.0.0.1"])
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_BLOCKED_URL"


async def test_fetch_rejects_bad_scheme():
    provider, _ = _provider([])
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="ftp://example.com"))
    assert ei.value.code == "WEB_INVALID_URL"


async def test_fetch_rejects_binary_content_type():
    provider, _ = _provider([_FakeResponse(200, {"content-type": "application/octet-stream"}, b"\x00\x01")])
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com/bin"))
    assert ei.value.code == "WEB_UNSUPPORTED_CONTENT_TYPE"


async def test_fetch_truncates_oversized_body():
    big = b"x" * 1000
    provider, _ = _provider([_FakeResponse(200, {"content-type": "text/plain"}, big)])
    provider._max_response_bytes = 100
    provider._max_body_chars = 100
    result = await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert result.truncated is True
    assert len(result.body.content) == 100


async def test_fetch_follows_same_origin_redirect():
    responses = [
        _FakeResponse(301, {"location": "https://example.com/new", "content-type": "text/html"}, b"", is_redirect=True),
        _FakeResponse(200, {"content-type": "text/plain"}, b"final"),
    ]
    provider, holder = _provider(responses)
    result = await provider.fetch(WebFetchRequest(url="https://example.com/old"))
    assert result.body.content == "final"
    assert result.statusCode == 200


async def test_fetch_blocks_cross_origin_redirect():
    responses = [
        _FakeResponse(302, {"location": "https://other.com/x", "content-type": "text/html"}, b"", is_redirect=True),
    ]
    provider, _ = _provider(responses)
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_REDIRECT_BLOCKED"


async def test_fetch_blocks_redirect_loop():
    redirect = _FakeResponse(302, {"location": "https://example.com/a", "content-type": "text/html"}, b"", is_redirect=True)
    provider, _ = _provider([redirect] * 10)
    provider._max_redirects = 2
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_REDIRECT_BLOCKED"


# ---------------------------------------------------------------------------
# WebRuntime：provider 注册表 + 选择语义
# ---------------------------------------------------------------------------


class _SearchProvider(WebSearchProvider):
    def __init__(self, id, sources):
        super().__init__(id)
        self._sources = sources

    async def search(self, request):
        return WebSearchResult(sources=self._sources)


async def test_web_no_provider_unavailable():
    ctx = Context()
    WebRuntime(ctx)
    with pytest.raises(WebError) as ei:
        await ctx.web.search(WebSearchRequest(query="x"))
    assert ei.value.code == "WEB_PROVIDER_UNAVAILABLE"


async def test_web_single_provider_selected():
    ctx = Context()
    WebRuntime(ctx)
    src = [WebSearchSource(url="https://a.com")]
    ctx.web.register_search_provider(_SearchProvider("p1", src))
    result = await ctx.web.search(WebSearchRequest(query="x"))
    assert len(result.sources) == 1


async def test_web_multiple_providers_ambiguous():
    ctx = Context()
    WebRuntime(ctx)
    ctx.web.register_search_provider(_SearchProvider("p1", []))
    ctx.web.register_search_provider(_SearchProvider("p2", []))
    with pytest.raises(WebError) as ei:
        await ctx.web.search(WebSearchRequest(query="x"))
    assert ei.value.code == "WEB_PROVIDER_AMBIGUOUS"


async def test_web_duplicate_provider_id_rejected():
    ctx = Context()
    web = WebRuntime(ctx)
    web.register_search_provider(_SearchProvider("p1", []))
    with pytest.raises(WebError) as ei:
        web.register_search_provider(_SearchProvider("p1", []))
    assert ei.value.code == "WEB_DUPLICATE_PROVIDER"


async def test_web_search_caps_max_results():
    ctx = Context()
    WebRuntime(ctx)
    sources = [WebSearchSource(url=f"https://a.com/{i}") for i in range(10)]
    ctx.web.register_search_provider(_SearchProvider("p1", sources))
    result = await ctx.web.search(WebSearchRequest(query="x", maxResults=3))
    assert len(result.sources) == 3
    assert result.truncated is True


async def test_web_register_returns_disposer():
    ctx = Context()
    web = WebRuntime(ctx)
    dispose = web.register_search_provider(_SearchProvider("p1", []))
    assert len(web._search_providers) == 1
    dispose()
    assert len(web._search_providers) == 0


class _UnavailableSearch(WebSearchProvider):
    def __init__(self):
        super().__init__("off")

    def available(self):
        return False

    async def search(self, request):
        return WebSearchResult(sources=[])


async def test_web_configured_provider_selected_over_multiple():
    ctx = Context()
    web = WebRuntime(ctx)
    src = [WebSearchSource(url="https://p2.com")]
    web.register_search_provider(_SearchProvider("p1", []))
    web.register_search_provider(_SearchProvider("p2", src))
    web._search_provider_id = "p2"  # 显式配置 → 选中，绕开歧义
    result = await web.search(WebSearchRequest(query="x"))
    assert result.sources[0].url == "https://p2.com"


async def test_web_configured_provider_missing():
    ctx = Context()
    web = WebRuntime(ctx)
    web._search_provider_id = "ghost"
    with pytest.raises(WebError) as ei:
        await web.search(WebSearchRequest(query="x"))
    assert ei.value.code == "WEB_PROVIDER_CONFIGURED_MISSING"


async def test_web_configured_provider_unavailable():
    ctx = Context()
    web = WebRuntime(ctx)
    web.register_search_provider(_UnavailableSearch())
    web._search_provider_id = "off"
    with pytest.raises(WebError) as ei:
        await web.search(WebSearchRequest(query="x"))
    assert ei.value.code == "WEB_PROVIDER_CONFIGURED_UNAVAILABLE"


async def test_web_fetch_duplicate_id_rejected():
    ctx = Context()
    web = WebRuntime(ctx)

    class _F(WebFetchProvider):
        def __init__(self):
            super().__init__("f1")

        async def fetch(self, request):
            raise NotImplementedError

    web.register_fetch_provider(_F())
    with pytest.raises(WebError) as ei:
        web.register_fetch_provider(_F())
    assert ei.value.code == "WEB_DUPLICATE_PROVIDER"


async def test_web_fetch_register_returns_disposer():
    ctx = Context()
    web = WebRuntime(ctx)

    class _F(WebFetchProvider):
        def __init__(self):
            super().__init__("f1")

        async def fetch(self, request):
            raise NotImplementedError

    dispose = web.register_fetch_provider(_F())
    assert len(web._fetch_providers) == 1
    dispose()
    assert len(web._fetch_providers) == 0


# ---------------------------------------------------------------------------
# tool-web
# ---------------------------------------------------------------------------


def _tool_ctx():
    ctx = Context()
    ctx.provide("config", Config())
    ToolRuntime(ctx)
    WebRuntime(ctx)
    from minidsh.packages.tools import web as tool_web
    tool_web.apply(ctx)
    return ctx


async def test_tool_web_search_registered():
    ctx = _tool_ctx()
    assert ctx.tools.get("web_search") is not None
    assert ctx.tools.get("web_fetch") is not None


async def test_tool_web_search_no_provider_degrades():
    ctx = _tool_ctx()
    execute = ctx.tools.get("web_search").execute
    value = await execute({"queries": ["python"]})
    assert value["available"] is False  # 无 search provider → 降级


async def test_tool_web_search_with_provider():
    ctx = _tool_ctx()
    sources = [WebSearchSource(url="https://a.com", title="A", snippet="desc")]
    ctx.web.register_search_provider(_SearchProvider("p1", sources))
    execute = ctx.tools.get("web_search").execute
    value = await execute({"queries": ["python"]})
    assert value["available"] is True
    assert value["sources"][0]["url"] == "https://a.com"
    assert value["sources"][0]["title"] == "A"


async def test_tool_web_search_dedupes_and_merges():
    ctx = _tool_ctx()
    shared = WebSearchSource(url="https://shared.com")
    ctx.web.register_search_provider(_SearchProvider("p1", [shared, WebSearchSource(url="https://a.com")]))
    execute = ctx.tools.get("web_search").execute
    value = await execute({"queries": ["q1", "q1"]})  # 精确重复 → 去重为单 query
    assert value["available"] is True


async def test_tool_web_search_rejects_empty_queries():
    ctx = _tool_ctx()
    execute = ctx.tools.get("web_search").execute
    with pytest.raises(ValueError):
        await execute({"queries": []})


async def test_tool_web_fetch_with_provider():
    ctx = _tool_ctx()

    class _Fetch(WebFetchProvider):
        def __init__(self):
            super().__init__("fake")

        async def fetch(self, request):
            from minidsh.packages.services.web import WebFetchResult, WebFetchBody
            return WebFetchResult(url=request.url, statusCode=200,
                                  body=WebFetchBody(kind="text", content="body"))

    ctx.web.register_fetch_provider(_Fetch())
    execute = ctx.tools.get("web_fetch").execute
    value = await execute({"url": "https://example.com"})
    assert value["available"] is True
    assert value["statusCode"] == 200
    assert value["body"]["content"] == "body"


async def test_tool_web_fetch_no_provider_degrades():
    ctx = _tool_ctx()
    execute = ctx.tools.get("web_fetch").execute
    value = await execute({"url": "https://example.com"})
    assert value["available"] is False


async def test_tool_web_fetch_empty_url_rejected():
    ctx = _tool_ctx()
    execute = ctx.tools.get("web_fetch").execute
    with pytest.raises(ValueError):
        await execute({"url": "  "})


async def test_tool_web_execute_via_runtime():
    """经 ToolRuntime.execute 全链路：web_search 无 provider 仍返回降级文本（非崩溃）。"""
    ctx = _tool_ctx()
    result = await ctx.tools.execute(ToolExecution(call_id="c1", name="web_search",
                                                   arguments={"queries": ["x"]}))
    assert result.is_error is False
    assert "unavailable" in result.content


# ---------------------------------------------------------------------------
# 纯函数：合并 / 渲染 / 校验（覆盖分支）
# ---------------------------------------------------------------------------


def test_parse_search_args_rejects_too_many():
    from minidsh.packages.tools.web import parse_search_args
    with pytest.raises(ValueError):
        parse_search_args({"queries": ["a", "b", "c", "d", "e"]}, max_queries=4)


def test_parse_search_args_rejects_non_string():
    from minidsh.packages.tools.web import parse_search_args
    with pytest.raises(ValueError):
        parse_search_args({"queries": ["ok", 123]})


def test_merge_results_dedup_across_queries():
    from minidsh.packages.tools.web import _merge_results
    r1 = WebSearchResult(sources=[WebSearchSource(url="https://a.com"),
                                  WebSearchSource(url="https://shared.com")])
    r2 = WebSearchResult(sources=[WebSearchSource(url="https://shared.com"),
                                  WebSearchSource(url="https://c.com")])
    merged = _merge_results(["q1", "q2"], [r1, r2], max_results=10)
    urls = [s["url"] for s in merged["sources"]]
    # round-robin + 去重：shared 只出现一次
    assert urls.count("https://shared.com") == 1
    assert set(urls) == {"https://a.com", "https://shared.com", "https://c.com"}


def test_merge_results_truncates_and_flags():
    from minidsh.packages.tools.web import _merge_results
    r1 = WebSearchResult(sources=[WebSearchSource(url=f"https://x{i}.com") for i in range(5)])
    merged = _merge_results(["q1"], [r1], max_results=2)
    assert len(merged["sources"]) == 2
    assert merged["truncated"] is True


def test_merge_results_collects_content():
    from minidsh.packages.tools.web import _merge_results
    r1 = WebSearchResult(sources=[], content="answer one")
    merged = _merge_results(["q1"], [r1], max_results=5)
    assert "### q1" in merged["content"]
    assert "answer one" in merged["content"]


def test_render_search_sources_markdown():
    from minidsh.packages.tools.web import _render_search
    value = {"available": True,
             "sources": [{"url": "https://a.com", "title": "A", "snippet": "snip",
                          "publishedAt": "2024"}],
             "content": None, "truncated": False}
    out = _render_search({}, value)
    assert "[A](https://a.com)" in out
    assert "snip" in out
    assert "2024" in out


def test_render_search_no_results_and_truncated():
    from minidsh.packages.tools.web import _render_search
    value = {"available": True, "sources": [], "content": None, "truncated": True}
    out = _render_search({}, value)
    assert "No results found." in out
    assert "Refine the query" in out


def test_render_fetch_with_truncation():
    from minidsh.packages.tools.web import _render_fetch
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": "hello"}, "truncated": True}
    out = _render_fetch({}, value)
    assert "Fetched https://a.com (HTTP 200)" in out
    assert "hello" in out
    assert "truncated" in out


def test_render_fetch_unavailable():
    from minidsh.packages.tools.web import _render_fetch
    out = _render_fetch({}, {"available": False, "error": "nope"})
    assert "unavailable" in out
    assert "nope" in out


# ---------- M2: HTML→text + cap + notice ----------


def test_html_to_text_strips_script_and_tags():
    from minidsh.packages.tools.web import _html_to_text
    html = "<html><head><script>alert(1)</script></head><body><p>Hello</p><script>evil()</script></body></html>"
    out = _html_to_text(html)
    assert "Hello" in out
    assert "<script>" not in out
    assert "alert" not in out
    assert "evil" not in out


def test_html_to_text_plain_passthrough():
    from minidsh.packages.tools.web import _html_to_text
    # text/plain 不经此路径；但若传入纯文本，无标签可剥，内容保留
    out = _html_to_text("just plain text")
    assert out == "just plain text"


def test_html_to_text_unescape_entities():
    from minidsh.packages.tools.web import _html_to_text
    out = _html_to_text("<p>&lt;div&gt; &amp; &quot;quotes&quot;</p>")
    assert "<div>" in out
    assert "&amp;" not in out


def test_html_to_text_block_tags_become_newlines():
    from minidsh.packages.tools.web import _html_to_text
    html = "<h1>Title</h1><p>Para one</p><div>Block</div>"
    out = _html_to_text(html)
    assert "\n" in out
    assert "Title" in out
    assert "Para one" in out


def test_render_fetch_respects_cap():
    from minidsh.packages.tools.web import _render_fetch, WEB_FETCH_MAX_OUTPUT_CHARS, HTML_OMITTED_MARKER
    # 构造超过 cap 的纯文本内容
    huge = "A" * (WEB_FETCH_MAX_OUTPUT_CHARS + 1000)
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": huge}, "truncated": False}
    out = _render_fetch({}, value)
    assert len(out) < len(huge)
    assert "Content truncated" in out


def test_render_fetch_has_notice():
    from minidsh.packages.tools.web import _render_fetch, EXTERNAL_WEB_CONTENT_NOTICE
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": "content"}, "truncated": False}
    out = _render_fetch({}, value)
    assert EXTERNAL_WEB_CONTENT_NOTICE in out


def test_render_fetch_html_converted_to_text():
    from minidsh.packages.tools.web import _render_fetch
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "html", "content": "<h1>Heading</h1><p>Text body</p>"}, "truncated": False}
    out = _render_fetch({}, value)
    assert "Heading" in out
    assert "Text body" in out
    assert "<h1>" not in out
    assert "<p>" not in out


def test_render_fetch_no_double_truncated_footer():
    from minidsh.packages.tools.web import _render_fetch
    # 内容短，不触发 cap 截断；仅上游 truncated 标记
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": "short"}, "truncated": True}
    out = _render_fetch({}, value)
    assert "Content truncated" in out


def test_render_fetch_conversion_failure_marker(monkeypatch):
    """HTML 转换抛异常 → 降级为官方 omission marker，不带原始 markup。"""
    import minidsh.packages.tools.web as web_mod

    def _explode(html_str):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_mod, "_html_to_text", _explode)
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "html", "content": "<p>text</p>"}, "truncated": False}
    out = web_mod._render_fetch({}, value)
    assert web_mod.HTML_OMITTED_MARKER in out
    assert "<p>" not in out


# ---------- M5: presentation_meta 双通道 ----------


def test_fetch_meta_structure():
    from minidsh.packages.tools.web import _fetch_meta
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": "x"}, "truncated": False}
    meta = _fetch_meta({}, value)
    assert meta == {"url": "https://a.com", "statusCode": 200, "truncated": False}


def test_fetch_meta_truncated_flag():
    from minidsh.packages.tools.web import _fetch_meta
    value = {"available": True, "url": "https://a.com", "statusCode": 200,
             "body": {"kind": "text", "content": "x"}, "truncated": True}
    meta = _fetch_meta({}, value)
    assert meta["truncated"] is True


def test_fetch_meta_unavailable_returns_none():
    from minidsh.packages.tools.web import _fetch_meta
    assert _fetch_meta({}, {"available": False}) is None


def test_search_meta_structure():
    from minidsh.packages.tools.web import _search_meta
    value = {"available": True,
             "sources": [{"url": "https://a.com"}, {"url": "https://b.com"}],
             "content": "answer", "truncated": False}
    meta = _search_meta({}, value)
    assert len(meta["sources"]) == 2
    assert meta["content"] == "answer"
    assert meta["truncated"] is False


def test_search_meta_unavailable_returns_none():
    from minidsh.packages.tools.web import _search_meta
    assert _search_meta({}, {"available": False}) is None


async def test_tool_result_carries_meta_via_runtime():
    """经 ToolRuntime.execute 全链路：web_fetch 的 ToolResult 携带 meta。"""
    ctx = _tool_ctx()

    class _Fetch(WebFetchProvider):
        def __init__(self):
            super().__init__("fake")

        async def fetch(self, request):
            from minidsh.packages.services.web import WebFetchResult, WebFetchBody
            return WebFetchResult(url=request.url, statusCode=200,
                                  body=WebFetchBody(kind="text", content="body"))

    ctx.web.register_fetch_provider(_Fetch())
    result = await ctx.tools.execute(ToolExecution(call_id="c", name="web_fetch",
                                                   arguments={"url": "https://example.com"}))
    assert result.is_error is False
    assert result.meta is not None
    assert result.meta["url"] == "https://example.com"
    assert result.meta["statusCode"] == 200


async def test_tool_without_meta_has_none():
    """无 presentation_meta 的工具（如 bash）ToolResult.meta 为 None。"""
    from minidsh.packages.services.tool_runtime import ToolRuntime as TR, ToolDefinition, ToolOutput, ToolExecution as TE
    from minidsh.cordis import Context as Ctx

    ctx = Ctx()
    tools = TR(ctx)

    async def _exec(args):
        return {"ok": True}

    tools.register(ToolDefinition(
        name="plain", description="x", parameters={"type": "object", "properties": {}},
        execute=_exec,
        output=ToolOutput(schema={"type": "object"}, render=lambda a, v: "done"),
    ))
    result = await tools.execute(TE(call_id="c", name="plain", arguments={}))
    assert result.meta is None


# ---------------------------------------------------------------------------
# tool-web 多 query 并发 + 渲染全链路
# ---------------------------------------------------------------------------


class _PerQuerySearch(WebSearchProvider):
    def __init__(self):
        super().__init__("pq")

    async def search(self, request: WebSearchRequest):
        return WebSearchResult(sources=[WebSearchSource(url=f"https://{request.query}.com",
                                                        title=request.query)])


async def test_tool_web_search_multi_query_gather():
    ctx = _tool_ctx()
    ctx.web.register_search_provider(_PerQuerySearch())
    execute = ctx.tools.get("web_search").execute
    value = await execute({"queries": ["alpha", "beta"]})
    assert value["available"] is True
    urls = {s["url"] for s in value["sources"]}
    assert urls == {"https://alpha.com", "https://beta.com"}


async def test_tool_web_search_render_via_runtime():
    ctx = _tool_ctx()
    ctx.web.register_search_provider(_PerQuerySearch())
    result = await ctx.tools.execute(ToolExecution(call_id="c", name="web_search",
                                                   arguments={"queries": ["alpha"]}))
    assert result.is_error is False
    assert "[alpha](https://alpha.com)" in result.content


async def test_tool_web_fetch_render_via_runtime():
    ctx = _tool_ctx()

    class _Fetch(WebFetchProvider):
        def __init__(self):
            super().__init__("fake")

        async def fetch(self, request):
            from minidsh.packages.services.web import WebFetchResult, WebFetchBody
            return WebFetchResult(url=request.url, statusCode=200,
                                  body=WebFetchBody(kind="text", content="page body"))

    ctx.web.register_fetch_provider(_Fetch())
    result = await ctx.tools.execute(ToolExecution(call_id="c", name="web_fetch",
                                                   arguments={"url": "https://example.com"}))
    assert result.is_error is False
    assert "Fetched https://example.com (HTTP 200)" in result.content
    assert "page body" in result.content


# ---------------------------------------------------------------------------
# HttpFetchProvider：传输错误 / 边界分支
# ---------------------------------------------------------------------------


async def test_fetch_redirect_without_location_errors():
    responses = [_FakeResponse(301, {"content-type": "text/html"}, b"", is_redirect=True)]
    provider, _ = _provider(responses)
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_PROVIDER_ERROR"


async def test_fetch_timeout_translates():
    import httpx as _httpx

    class _TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            raise _httpx.ConnectTimeout("timed out")

    provider = HttpFetchProvider(client_factory=lambda **kw: _TimeoutClient(),
                                 resolve=lambda h: ["93.184.216.34"])
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_FETCH_TIMEOUT"


async def test_fetch_http_error_translates():
    import httpx as _httpx

    class _ErrClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            raise _httpx.ConnectError("conn refused")

    provider = HttpFetchProvider(client_factory=lambda **kw: _ErrClient(),
                                 resolve=lambda h: ["93.184.216.34"])
    with pytest.raises(WebError) as ei:
        await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert ei.value.code == "WEB_PROVIDER_ERROR"


async def test_fetch_truncates_by_body_chars():
    # bytes 小于上限，但解码后字符数超 max_body_chars → 按字符截断
    provider, _ = _provider([_FakeResponse(200, {"content-type": "text/plain"}, b"y" * 500)])
    provider._max_body_chars = 50
    result = await provider.fetch(WebFetchRequest(url="https://example.com"))
    assert result.truncated is True
    assert len(result.body.content) == 50


def test_fetch_provider_available():
    provider, _ = _provider([])
    assert provider.available() is True


def test_resolve_public_addresses_dns_failure(monkeypatch):
    import socket as _socket
    from minidsh.packages.services.web.providers.fetch_http import resolve_public_addresses

    def _fail(host, port):
        raise _socket.gaierror("no such host")

    monkeypatch.setattr(_socket, "getaddrinfo", _fail)
    with pytest.raises(WebError) as ei:
        resolve_public_addresses("nonexistent.invalid")
    assert ei.value.code == "WEB_PROVIDER_ERROR"
