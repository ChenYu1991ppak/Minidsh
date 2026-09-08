"""rpc 能力：跨进程 RPC seam（seam 预留）。

v1 为纯标记 seam：声明 RpcGateway 接口 + NoopRpcGateway 实现，
为未来跨进程委派/外部驱动预留。
"""
from __future__ import annotations

from .definition import RpcGateway, NoopRpcGateway

__all__ = ['RpcGateway', 'NoopRpcGateway']
