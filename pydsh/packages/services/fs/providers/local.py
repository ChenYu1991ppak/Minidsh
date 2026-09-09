"""fs 的本地 provider（三角色的「提供方」）：文件读写。

对齐官方能力三层拆分的 provider：实现 FsService，经 module 插件 provide 到 ctx.fs。
↔ packages/fs/dsh-fs-local：本地文件系统后端。
"""
from __future__ import annotations

import os

from ..definition import FsRequest, FsResult, FsService
from pydsh.cordis import CapabilityProvider

__all__ = ["LocalFsService"]

name = "pydsh.fs-local"
inject = []


class LocalFsService(FsService, CapabilityProvider):
    """本地文件读写。[教学简化] 无路径沙箱，安全边界交 guard 层。"""

    async def execute(self, request: FsRequest) -> FsResult:
        with open(request.path, encoding="utf-8") as f:
            content = f.read()
        return FsResult(content=content)

    async def write_text(self, path: str, content: str) -> None:
        """写入文本文件（覆盖已有）。[教学简化] 无原子写入、无 fsync。"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def edit_text(self, path: str, old_string: str, new_string: str,
                        replace_all: bool = False) -> str:
        """基于字符串替换编辑文件。返回替换后的完整文本。

        ``replace_all=True`` 替换所有匹配项；默认仅替换第一个。
        [教学简化] 无 diff 展示、无 ambiguous-edit 检测。
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            text = ""
        if replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)
        if not text and not new_text:
            # 文件不存在：当作创建新文件，直接写入 new_string
            new_text = new_string
        if not text and not new_text:
            # 文件不存在：当作创建新文件，直接写入 new_string
            new_text = new_string
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return new_text


def apply(ctx):
    LocalFsService(ctx)  # 构造即注册 ctx.fs