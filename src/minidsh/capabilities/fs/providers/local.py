"""fs 的本地 provider（三角色的「提供方」）：open 读文件。

对齐官方能力三层拆分的 provider：实现 FsService，经 module 插件 provide 到 ctx.fs。
"""
from __future__ import annotations

from ..definition import FsRequest, FsResult, FsService
from ....cordis import CapabilityProvider

__all__ = ["LocalFsService"]

name = "minidsh.fs-local"
inject = []


class LocalFsService(FsService, CapabilityProvider):
    """本地读文件。[教学简化] 无路径沙箱，安全边界交 guard 层。"""

    async def execute(self, request: FsRequest) -> FsResult:
        with open(request.path, encoding="utf-8") as f:
            content = f.read()
        return FsResult(content=content)


def apply(ctx):
    LocalFsService(ctx)  # 构造即注册 ctx.fs