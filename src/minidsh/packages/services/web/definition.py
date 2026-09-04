"""web 能力定义：检索 seam（ctx.web）。

源码对应：
- ``WebSearchProvider`` / ``WebFetchProvider`` ↔ packages/web/web/src/types.ts
- ``WebRuntime`` ↔ packages/web/web/src/index.ts（provider 注册表 + 选择语义）
- ``WebError`` ↔ packages/web/web/src/types.ts（结构化错误码）

WebRuntime 管理 search/fetch 两类 provider 的注册与选择。选择语义：
- 配置了 id 且已注册且 available() → 该 provider
- 配置了 id 未注册 → WEB_PROVIDER_CONFIGURED_MISSING
- 配置了 id 已注册但不可用 → WEB_PROVIDER_CONFIGURED_UNAVAILABLE
- 未配置 id，恰好一个可用 → 该 provider
- 未配置 id，多个可用 → WEB_PROVIDER_AMBIGUOUS
- 未配置 id，无可用 → WEB_PROVIDER_UNAVAILABLE

[教学简化] 不实现 AbortSignal 取消（Python 无内置 AbortSignal）；不实现
WebRuntimeConfig（无 schemastery 校验层）；WebSearchProvider 无 available() 方法
（provider 注册即视为可用）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from minidsh.cordis import CapabilityProvider

__all__ = [
    "WebSearchRequest",
    "WebSearchResult",
    "WebSearchSource",
    "WebFetchRequest",
    "WebFetchResult",
    "WebFetchBody",
    "WebSearchProvider",
    "WebFetchProvider",
    "WebRuntime",
    "WebError",
]

# ---------------------------------------------------------------------------
# 请求/结果类型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebSearchRequest:
    """一次搜索请求：query + 可选 maxResults 上限。"""

    query: str
    maxResults: int | None = None


@dataclass(frozen=True)
class WebSearchSource:
    """一条可引用来源。url 必有；title/snippet/publishedAt 可选。"""

    url: str
    title: str | None = None
    snippet: str | None = None
    publishedAt: str | None = None


@dataclass(frozen=True)
class WebSearchResult:
    """归一化搜索结果：sources[] + 可选 content（provider 生成的回答文本）+ truncated 标记。"""

    sources: list[WebSearchSource] = field(default_factory=list)
    content: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class WebFetchRequest:
    """一次抓取请求：目标 URL。"""

    url: str


@dataclass(frozen=True)
class WebFetchBody:
    """解码后的响应体。kind: 'html' | 'text'。"""

    kind: Literal["html", "text"]
    content: str


@dataclass(frozen=True)
class WebFetchResult:
    """归一化抓取结果。非 2xx 为结果非错误；statusCode 是资源状态的一部分。"""

    url: str
    statusCode: int
    body: WebFetchBody
    truncated: bool = False


# ---------------------------------------------------------------------------
# Provider 接口
# ---------------------------------------------------------------------------


class WebSearchProvider:
    """搜索后端。注册到 ctx.web.registerSearchProvider。"""

    def __init__(self, id: str):
        self.id = id

    def available(self) -> bool:
        """本地可用性检查（不得有网络调用）。"""
        return True

    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        raise NotImplementedError


class WebFetchProvider:
    """抓取后端。注册到 ctx.web.registerFetchProvider。"""

    def __init__(self, id: str):
        self.id = id

    def available(self) -> bool:
        """本地可用性检查（不得有网络调用）。"""
        return True

    async def fetch(self, request: WebFetchRequest) -> WebFetchResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# WebError
# ---------------------------------------------------------------------------


class WebError(Exception):
    """结构化 web 错误：code 为机器可路由的错误码。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# WebRuntime
# ---------------------------------------------------------------------------


def _resolve_provider(providers: dict[str, "WebSearchProvider | WebFetchProvider"],
                       configured_id: str | None,
                       kind: str) -> "WebSearchProvider | WebFetchProvider":
    """按选择语义解析 provider；找不到时抛 WebError。"""
    if configured_id is not None:
        provider = providers.get(configured_id)
        if provider is None:
            raise WebError(
                f"configured web {kind} provider \"{configured_id}\" is not registered",
                "WEB_PROVIDER_CONFIGURED_MISSING",
            )
        if not provider.available():
            raise WebError(
                f"configured web {kind} provider \"{configured_id}\" is registered but unavailable",
                "WEB_PROVIDER_CONFIGURED_UNAVAILABLE",
            )
        return provider

    usable = [p for p in providers.values() if p.available()]
    if not usable:
        raise WebError(
            f"no usable web {kind} provider is registered",
            "WEB_PROVIDER_UNAVAILABLE",
        )
    if len(usable) > 1:
        ids = ", ".join(p.id for p in usable)
        raise WebError(
            f"multiple usable web {kind} providers are registered ({ids}); configure one explicitly",
            "WEB_PROVIDER_AMBIGUOUS",
        )
    return usable[0]


class WebRuntime(CapabilityProvider):
    """ctx.web：检索 seam。管理 search/fetch provider 注册表 + 选择语义。

    构造即注册 ctx.web（对齐 ToolRuntime 的 provider 形态）；base 插件 ``minidsh.web``
    实例化它，web-fetch-http / tool-web 等消费方经 ctx.web 注册 provider 或调用。
    """

    service_name = "web"

    def _init(self, ctx):
        self._search_providers: dict[str, WebSearchProvider] = {}
        self._fetch_providers: dict[str, WebFetchProvider] = {}
        self._search_provider_id: str | None = None
        self._fetch_provider_id: str | None = None

    # ---------- 注册 ----------

    def register_search_provider(self, provider: WebSearchProvider):
        """注册搜索 provider；返回 disposer。id 重复时抛 WebError。"""
        if provider.id in self._search_providers:
            raise WebError(
                f"a web search provider with id \"{provider.id}\" is already registered",
                "WEB_DUPLICATE_PROVIDER",
            )
        self._search_providers[provider.id] = provider

        def dispose():
            self._search_providers.pop(provider.id, None)

        return dispose

    def register_fetch_provider(self, provider: WebFetchProvider):
        """注册抓取 provider；返回 disposer。id 重复时抛 WebError。"""
        if provider.id in self._fetch_providers:
            raise WebError(
                f"a web fetch provider with id \"{provider.id}\" is already registered",
                "WEB_DUPLICATE_PROVIDER",
            )
        self._fetch_providers[provider.id] = provider

        def dispose():
            self._fetch_providers.pop(provider.id, None)

        return dispose

    # ---------- 执行 ----------

    async def search(self, request: WebSearchRequest) -> WebSearchResult:
        """执行搜索：选 provider → 调 search → 按 maxResults 截断。"""
        provider = _resolve_provider(
            self._search_providers,  # type: ignore[arg-type]
            self._search_provider_id,
            "search",
        )
        result = await provider.search(request)  # type: ignore[union-attr]
        if request.maxResults is not None and len(result.sources) > request.maxResults:
            return WebSearchResult(
                sources=result.sources[:request.maxResults],
                content=result.content,
                truncated=True,
            )
        return result

    async def fetch(self, request: WebFetchRequest) -> WebFetchResult:
        """执行抓取：选 provider → 调 fetch。非 2xx 为结果非错误。"""
        provider = _resolve_provider(
            self._fetch_providers,  # type: ignore[arg-type]
            self._fetch_provider_id,
            "fetch",
        )
        return await provider.fetch(request)  # type: ignore[union-attr]