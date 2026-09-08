"""web-search-ddg provider：DuckDuckGo HTML 搜索（零 API key，对齐官方 search provider）。

源码对应：
- ``DdgSearchProvider`` ↔ packages/web/web-search-* 搜索 provider 实现
- 策略函数为纯函数，无网络依赖

[教学简化] 用 DuckDuckGo HTML 搜索（lite 版），无需 API key。解析 HTML 提取
标题/摘要/URL。非官方搜索结果页结构，仅提取结构化链接。
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import httpx

from ..definition import (
    WebSearchProvider,
    WebSearchRequest,
    WebSearchResult,
    WebSearchSource,
    WebError,
)

__all__ = ["DdgSearchProvider", "DDG_SEARCH_PROVIDER_ID"]

DDG_SEARCH_PROVIDER_ID = "ddg"

# DuckDuckGo HTML 搜索 URL（lite 版，返回简洁 HTML）
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

# User-Agent
_DDG_USER_AGENT = "mini-dsh/0.1 (+https://github.com/mini-dsh)"

# 结果上限
_MAX_RESULTS = 20


def _parse_ddg_html(html: str) -> list[WebSearchSource]:
    """从 DuckDuckGo lite HTML 中提取搜索结果。

    每条结果格式：
    <a rel="nofollow" href="..." class="result-link">标题</a>
    <span class="result-snippet">摘要</span>
    """
    sources: list[WebSearchSource] = []
    # 匹配 <a rel="nofollow" class="result-link" href="URL">title</a>
    # 和紧随的 <span class="result-snippet">snippet</span>
    pattern = re.compile(
        r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?'
        r'<span[^>]*class="result-snippet"[^>]*>(.*?)</span>',
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        url = m.group(1)
        title = _strip_html(m.group(2)).strip()
        snippet = _strip_html(m.group(3)).strip()
        if url and title:
            sources.append(WebSearchSource(
                url=url,
                title=title,
                snippet=snippet if snippet else None,
            ))
    return sources[: _MAX_RESULTS]


def _strip_html(text: str) -> str:
    """剥去 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", text)


class DdgSearchProvider(WebSearchProvider):
    """DuckDuckGo 搜索 provider（id="ddg"），零 API key。

    [教学简化] 用 DuckDuckGo lite HTML 搜索，非官方 API；无 available() 网络检查。
    """

    def __init__(
        self,
        timeout_s: float = 15.0,
        user_agent: str = _DDG_USER_AGENT,
        client_factory=None,
    ):
        super().__init__(DDG_SEARCH_PROVIDER_ID)
        self._timeout_s = timeout_s
        self._user_agent = user_agent
        self._client_factory = client_factory or httpx.AsyncClient

    def available(self) -> bool:
        return True

    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        """执行 DuckDuckGo 搜索：请求 HTML → 解析结果 → 返回 WebSearchResult。"""
        encoded = quote_plus(request.query)
        url = f"{_DDG_LITE_URL}?q={encoded}"

        headers = {"user-agent": self._user_agent}

        try:
            async with self._client_factory(follow_redirects=True, timeout=self._timeout_s) as client:
                resp = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise WebError("DuckDuckGo search timed out", "WEB_SEARCH_TIMEOUT") from exc
        except httpx.HTTPError as exc:
            raise WebError(f"DuckDuckGo search failed: {exc}", "WEB_PROVIDER_ERROR") from exc

        if resp.status_code != 200:
            raise WebError(
                f"DuckDuckGo returned HTTP {resp.status_code}",
                "WEB_PROVIDER_ERROR",
            )

        sources = _parse_ddg_html(resp.text)
        return WebSearchResult(
            sources=sources,
            truncated=len(sources) >= _MAX_RESULTS,
        )


# ---------------------------------------------------------------------------
# base 插件入口：minidsh.web-search-ddg（注入 web，注册 DdgSearchProvider）
# ---------------------------------------------------------------------------

name = "minidsh.web-search-ddg"
inject = ["web"]


def apply(ctx):
    ctx.web.register_search_provider(DdgSearchProvider())