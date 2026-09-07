"""base 插件：lsp（提供 ctx.lsp 语义 seam + 注册 noop 桩）。

对齐官方 ``dsh-lsp`` 的 LspService：构造即注册 ``ctx.lsp``，并注册 NoopLspProvider
作为默认桩（四操作空结果）。tool-lsp 消费方经 ctx.lsp.query 调用。

[教学简化] provider 留桩：后续接真 stdio language server 时，新增 LspProvider 子类
注册即可（需先移除 noop 对应扩展名，或让真 provider 用不同扩展名集）。
"""
from __future__ import annotations

from minidsh.packages.services.lsp import LspService
from minidsh.packages.services.lsp.providers.noop import NoopLspProvider

name = "minidsh.lsp"
inject: list[str] = []


def apply(ctx):
    lsp = LspService(ctx)  # 构造即注册 ctx.lsp
    lsp.register_provider(NoopLspProvider())
