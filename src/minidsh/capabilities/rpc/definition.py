"""rpc 模块：跨进程 RPC seam（seam 预留）。

对应 ch16 的 typert/api/sdk（typed cross-process RPC runtime）。v1 为纯标记
seam：声明 ``RpcGateway`` 接口与 ``NoopRpcGateway`` 实现（不开启、不转发），
为未来跨进程委派/外部驱动预留位置。

扩展方式：定义 ``RpcGateway`` 子类覆写 ``start`` / ``handle`` / ``request``。
"""
from __future__ import annotations

from ...cordis import Service

__all__ = ["RpcGateway", "NoopRpcGateway"]


class RpcGateway(Service):
    """跨进程 RPC 网关定义（seam）。no-op 不开启服务。"""

    def __init__(self, ctx):
        super().__init__(ctx, "rpc")

    async def start(self) -> None:
        """开启网关。no-op 不监听。"""
        return None

    async def request(self, method: str, params: dict) -> dict:
        """发起请求。no-op 返回不可用。"""
        return {"available": False, "method": method}


class NoopRpcGateway(RpcGateway):
    """显式 no-op 命名实现。"""

    pass