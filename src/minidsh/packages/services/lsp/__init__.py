"""lsp 能力：代码语义 seam（ctx.lsp）。

四操作（goToDefinition / findReferences / goToImplementation / hover）+ provider 注册表。
"""
from __future__ import annotations

from .definition import (
    LspOperation,
    LspPosition,
    LspRange,
    LspQueryRequest,
    LspProviderQuery,
    LspLocation,
    LspHover,
    LspQueryResult,
    LspProvider,
    LspService,
    LspError,
    final_extension,
    LSP_OPERATIONS,
)

__all__ = [
    "LspOperation",
    "LspPosition",
    "LspRange",
    "LspQueryRequest",
    "LspProviderQuery",
    "LspLocation",
    "LspHover",
    "LspQueryResult",
    "LspProvider",
    "LspService",
    "LspError",
    "final_extension",
    "LSP_OPERATIONS",
]