"""web 模块：检索 seam（seam 预留）。

对应 ch13 的 ctx.web（search/fetch）。v1 为 no-op：search/fetch 均返回
「不可用」标记，为未来接真实检索/抓取 provider 预留接口。

三角色：``WebService`` 是定义（纯接口），``NoopWebService`` 是 provider（构造即注册 ctx.web）。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition, CapabilityProvider

__all__ = ["WebService", "NoopWebService"]


class WebService(CapabilityDefinition):
    """web 检索服务定义（seam）。"""

    service_name = "web"

    def search(self, query: str) -> dict:
        raise NotImplementedError

    def fetch(self, url: str) -> dict:
        raise NotImplementedError


class NoopWebService(WebService, CapabilityProvider):
    """显式 no-op provider：返回不可用标记，构造即注册 ctx.web。"""

    def search(self, query: str) -> dict:
        return {"available": False, "query": query, "results": []}

    def fetch(self, url: str) -> dict:
        return {"available": False, "url": url, "content": ""}