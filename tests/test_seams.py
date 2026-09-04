"""T19 验收测试：seam 预留模块（approval/web/lsp/rpc）契约存在 + 可扩展。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.approval import ApprovalProvider
from minidsh.packages.services.web import WebRuntime, WebFetchProvider, WebFetchRequest, WebFetchResult, WebFetchBody
from minidsh.packages.services.lsp import LspService, LspProvider, LspQueryRequest, LspPosition, LspQueryResult
from minidsh.packages.services.rpc import RpcGateway, NoopRpcGateway


async def test_approval_seam_policy_never():
    ctx = Context()
    ApprovalProvider(ctx)  # provider 构造即注册 ctx.approval
    ctx.approval.set_policy("never")
    from minidsh.packages.services.approval import ApprovalRequest
    req = ApprovalRequest(agent=type("A", (), {"session": None})(), tool_name="bash")
    outcome = await ctx.approval.request(req)
    assert outcome == "rejected"


async def test_approval_seam_ask_unavailable():
    ctx = Context()
    ApprovalProvider(ctx)
    from minidsh.packages.services.approval import ApprovalRequest
    req = ApprovalRequest(agent=type("A", (), {"session": None})(), tool_name="bash")
    outcome = await ctx.approval.request(req)
    assert outcome == "unavailable"  # 无应答者 → fail-closed


async def test_web_seam_registers_and_selects_provider():
    ctx = Context()
    WebRuntime(ctx)  # 构造即注册 ctx.web
    assert ctx.has("web")

    # 无 provider → WEB_PROVIDER_UNAVAILABLE
    from minidsh.packages.services.web import WebError
    try:
        await ctx.web.fetch(WebFetchRequest(url="http://example.com"))
        assert False, "应该抛 WEB_PROVIDER_UNAVAILABLE"
    except WebError as exc:
        assert exc.code == "WEB_PROVIDER_UNAVAILABLE"

    # 注册一个 fetch provider → 正常返回
    class _FakeFetch(WebFetchProvider):
        def __init__(self):
            super().__init__("fake")

        async def fetch(self, request: WebFetchRequest) -> WebFetchResult:
            return WebFetchResult(
                url=request.url, statusCode=200,
                body=WebFetchBody(kind="text", content="hello"),
            )

    ctx.web.register_fetch_provider(_FakeFetch())
    result = await ctx.web.fetch(WebFetchRequest(url="http://example.com"))
    assert result.body.content == "hello"


async def test_lsp_seam_registers_and_queries():
    ctx = Context()
    LspService(ctx)  # 构造即注册 ctx.lsp
    assert ctx.has("lsp")

    class _FakeLsp(LspProvider):
        id = "fake"
        extensionToLanguage = {".py": "python"}

        async def query(self, request):
            return LspQueryResult(kind="locations", locations=[])

    ctx.lsp.register_provider(_FakeLsp())
    result = await ctx.lsp.query(LspQueryRequest(
        operation="goToDefinition", filePath="f.py",
        position=LspPosition(line=0, character=0),
    ))
    assert result.kind == "locations"
    assert result.locations == []


async def test_rpc_seam_noop():
    ctx = Context()
    NoopRpcGateway(ctx)
    await ctx.rpc.start()  # no-op，不抛错
    result = await ctx.rpc.request("greet", {})
    assert result["available"] is False


def test_all_seams_registered_by_name():
    """四个预留 seam 都以具名 Service 存在（spec S7：seam 可注册可扩展）。"""
    ctx = Context()
    ApprovalProvider(ctx)
    WebRuntime(ctx)
    LspService(ctx)
    NoopRpcGateway(ctx)
    for name in ("approval", "web", "lsp", "rpc"):
        assert ctx.has(name), f"缺 seam 服务 {name}"