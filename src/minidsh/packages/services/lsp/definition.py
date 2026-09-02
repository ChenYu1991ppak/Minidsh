"""lsp 模块：代码语义 seam（seam 预留）。

对应 ch13 的 ctx.lsp（归一化四操作查询）。v1 为 no-op：四操作均返回空，
为未来接 language server 语义能力预留接口。

三角色：``LspService`` 是定义（纯接口），``NoopLspService`` 是 provider（构造即注册 ctx.lsp）。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition, CapabilityProvider

__all__ = ["LspService", "NoopLspService"]


class LspService(CapabilityDefinition):
    """lsp 语义服务定义（seam）。"""

    service_name = "lsp"

    def definition(self, path: str, line: int, col: int) -> dict | None:
        raise NotImplementedError

    def references(self, path: str, line: int, col: int) -> list[dict]:
        raise NotImplementedError

    def hover(self, path: str, line: int, col: int) -> str | None:
        raise NotImplementedError

    def completions(self, path: str, line: int, col: int) -> list[str]:
        raise NotImplementedError


class NoopLspService(LspService, CapabilityProvider):
    """显式 no-op provider：四操作返回空，构造即注册 ctx.lsp。"""

    def definition(self, path, line, col):
        return None

    def references(self, path, line, col):
        return []

    def hover(self, path, line, col):
        return None

    def completions(self, path, line, col):
        return []