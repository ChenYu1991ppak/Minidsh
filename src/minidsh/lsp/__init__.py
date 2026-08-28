"""lsp 模块：代码语义 seam（seam 预留）。

对应 ch13 的 ctx.lsp（归一化四操作查询）。v1 为 no-op：四操作均返回空，
为未来接 language server 语义能力预留接口。

扩展方式：定义 ``LspService`` 子类覆写四个查询操作（definition/references/
hover/completions）。
"""
from __future__ import annotations

from ..cordis import Service

__all__ = ["LspService", "NoopLspService"]


class LspService(Service):
    """lsp 语义服务定义（seam）。"""

    def __init__(self, ctx):
        super().__init__(ctx, "lsp")

    def definition(self, path: str, line: int, col: int) -> dict | None:
        return None

    def references(self, path: str, line: int, col: int) -> list[dict]:
        return []

    def hover(self, path: str, line: int, col: int) -> str | None:
        return None

    def completions(self, path: str, line: int, col: int) -> list[str]:
        return []


class NoopLspService(LspService):
    """显式 no-op 命名实现。"""

    pass