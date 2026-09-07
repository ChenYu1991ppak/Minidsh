"""rpc 模块：跨进程 RPC seam（seam 预留）。

对应 ch16 的 typert/api/sdk（typed cross-process RPC runtime）。v1 为纯标记
seam：声明 ``RpcGateway`` 接口与 ``NoopRpcGateway`` 实现（不开启、不转发），
为未来跨进程委派/外部驱动预留位置。

三角色：``RpcGateway`` 是定义（纯接口），``NoopRpcGateway`` 是 provider（构造即注册 ctx.rpc）。
"""
from __future__ import annotations

from minidsh.cordis import CapabilityDefinition, CapabilityProvider

__all__ = ["RpcGateway", "NoopRpcGateway"]


class RpcGateway(CapabilityDefinition):
    """跨进程 RPC 网关定义（seam）。"""

    service_name = "rpc"

    async def start(self) -> None:
        raise NotImplementedError

    async def request(self, method: str, params: dict) -> dict:
        raise NotImplementedError


class NoopRpcGateway(RpcGateway, CapabilityProvider):
    """显式 no-op provider：不开启、不转发，构造即注册 ctx.rpc。"""

    async def start(self) -> None:
        return None

    async def request(self, method: str, params: dict) -> dict:
        return {"available": False, "method": method}