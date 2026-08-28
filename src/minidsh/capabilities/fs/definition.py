"""fs 能力定义：读文件的能力（三角色的「定义」）。

对齐官方能力三层拆分：定义 Service + Request/Result 类型。
Provider（如 local / 远端 / 内存）与 Consumer（tool-read）都只依赖本定义。
"""
from __future__ import annotations

from dataclasses import dataclass

from ...cordis import Service

__all__ = ["FsRequest", "FsResult", "FsService"]


@dataclass(frozen=True)
class FsRequest:
    """一次读文件请求。"""

    path: str


@dataclass(frozen=True)
class FsResult:
    """读文件结果（文本内容）。"""

    content: str


class FsService(Service):
    """ctx.fs：读文件的能力定义。多个 provider 可替换实现。"""

    async def execute(self, request: FsRequest) -> FsResult:
        raise NotImplementedError