"""fs 能力定义：文件读写的能力（三角色的「定义」）。

对齐官方能力三层拆分：定义 Service + Request/Result 类型。
Provider（如 local / 远端 / 内存）与 Consumer（tool-read / tool-write / tool-edit）
都只依赖本定义。

↔ packages/fs/dsh-fs（Write/Edit/Read 三合一 seam）
"""
from __future__ import annotations

from dataclasses import dataclass

from pydsh.cordis import CapabilityDefinition

__all__ = ["FsRequest", "FsResult", "FsService"]


@dataclass(frozen=True)
class FsRequest:
    """一次读文件请求。"""

    path: str


@dataclass(frozen=True)
class FsResult:
    """读文件结果（文本内容）。"""

    content: str


class FsService(CapabilityDefinition):
    """ctx.fs：文件读写的能力定义。多个 provider 可替换实现。

    ↔ packages/fs/dsh-fs：官方 Write/Edit/Read 三合一 seam。
    """

    service_name = "fs"

    async def execute(self, request: FsRequest) -> FsResult:
        raise NotImplementedError

    async def write_text(self, path: str, content: str) -> None:
        """写入文本文件（覆盖已有）。"""
        raise NotImplementedError

    async def edit_text(self, path: str, old_string: str, new_string: str,
                        replace_all: bool = False) -> str:
        """基于字符串替换编辑文件。返回替换后的完整文本。

        ``replace_all=True`` 替换所有匹配项；默认仅替换第一个。
        [教学简化] 无官方 diff 展示、无 sandbox escalation 字段。
        """
        raise NotImplementedError