"""web 能力：检索 seam（ctx.web）。

管理 search/fetch provider 注册表 + 选择语义。
"""
from __future__ import annotations

from .definition import (
    WebSearchRequest,
    WebSearchResult,
    WebSearchSource,
    WebFetchRequest,
    WebFetchResult,
    WebFetchBody,
    WebSearchProvider,
    WebFetchProvider,
    WebRuntime,
    WebError,
)

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