"""T19 验收测试：seam 预留模块（permission/web/lsp/rpc）git契约存在 + no-op 可扩展。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.permission import ApprovalService, AllowAllApprovalService
from minidsh.packages.services.web import WebService, NoopWebService
from minidsh.packages.services.lsp import LspService, NoopLspService
from minidsh.packages.services.rpc import RpcGateway, NoopRpcGateway


def test_permission_seam_noop_allows():
    ctx = Context()
    AllowAllApprovalService(ctx)  # provider 构造即注册 ctx.permission
    assert ctx.permission.approve("bash", {"cmd": "ls"}) is True


def test_permission_seam_async_denies():
    import pytest

    ctx = Context()
    AllowAllApprovalService(ctx)

    async def run():
        return await ctx.permission.ask("bash", {"cmd": "rm -rf"})

    import asyncio
    assert asyncio.run(run()) is False  # 无人工 → 降级 deny


def test_web_seam_noop():
    ctx = Context()
    NoopWebService(ctx)
    assert ctx.web.search("x")["available"] is False
    assert ctx.web.fetch("http://x")["content"] == ""


def test_lsp_seam_noop():
    ctx = Context()
    NoopLspService(ctx)
    assert ctx.lsp.definition("f.py", 1, 1) is None
    assert ctx.lsp.references("f.py", 1, 1) == []


async def test_rpc_seam_noop():
    ctx = Context()
    NoopRpcGateway(ctx)
    await ctx.rpc.start()  # no-op，不抛错
    result = await ctx.rpc.request("greet", {})
    assert result["available"] is False


def test_all_seams_registered_by_name():
    """四个预留 seam 都以具名 Service 存在（spec S7：no-op 但具名可扩展）。"""
    ctx = Context()
    AllowAllApprovalService(ctx)
    NoopWebService(ctx)
    NoopLspService(ctx)
    NoopRpcGateway(ctx)
    for name in ("permission", "web", "lsp", "rpc"):
        assert ctx.has(name), f"缺 seam 服务 {name}"