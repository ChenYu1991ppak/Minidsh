"""NoopLspProvider：四操作全返回空结果的桩 provider。

对齐官方「provider 留桩」：不接真 language-server stdio 二进制，四操作返回空
（``locations=[]`` / ``hover=None``），``available()`` 返回 False 标记其为桩。

[教学简化] 后续接真 stdio language server 时，新增一个 ``LspProvider`` 子类并经
``ctx.lsp.register_provider`` 注册即可，无需改 seam。
"""
from __future__ import annotations

from ..definition import LspProvider, LspQueryResult, LspProviderQuery

__all__ = ["NoopLspProvider"]

NOOP_LSP_PROVIDER_ID = "noop"


class NoopLspProvider(LspProvider):
    """四操作返回空结果的桩 provider（available=False）。"""

    id = NOOP_LSP_PROVIDER_ID
    extensionToLanguage = {
        ".py": "python",
        ".ts": "typescript",
        ".js": "javascript",
        ".go": "go",
        ".rs": "rust",
    }

    def available(self) -> bool:
        return False  # 桩：非真 language server

    async def query(self, request: LspProviderQuery) -> LspQueryResult:
        if request.operation == "hover":
            return LspQueryResult(kind="hover", hover=None)
        return LspQueryResult(kind="locations", locations=[])