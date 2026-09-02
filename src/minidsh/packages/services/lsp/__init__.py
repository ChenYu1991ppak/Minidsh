"""lsp 能力：代码语义 seam（seam 预留）。

v1 为 no-op：四操作（definition/references/hover/completions）返回空，
为未来接 language server 语义能力预留。
"""
from __future__ import annotations

from .definition import LspService, NoopLspService

__all__ = ['LspService', 'NoopLspService']
