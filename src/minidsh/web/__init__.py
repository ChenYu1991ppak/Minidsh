"""web 模块：检索 seam（seam 预留）。

对应 ch13 的 ctx.web（search/fetch）。v1 为 no-op：search/fetch 均返回
「不可用」标记，为未来接真实检索/抓取 provider 预留接口。

扩展方式：定义 ``WebService`` 子类覆写 ``search`` / ``fetch``。
"""
from __future__ import annotations

from ..cordis import Service

__all__ = ["WebService", "NoopWebService"]


class WebService(Service):
    """web 检索服务定义（seam）。"""

    def __init__(self, ctx):
        super().__init__(ctx, "web")

    def search(self, query: str) -> dict:
        """搜索。no-op 返回不可用标记。"""
        return {"available": False, "query": query, "results": []}

    def fetch(self, url: str) -> dict:
        """抓取。no-op 返回不可用标记。"""
        return {"available": False, "url": url, "content": ""}


class NoopWebService(WebService):
    """显式 no-op 命名实现。"""

    pass