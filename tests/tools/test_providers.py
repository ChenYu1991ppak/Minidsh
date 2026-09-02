"""CT3 验收测试：shell/fs 的 provider。"""
from __future__ import annotations

from minidsh.cordis import Context
from minidsh.packages.services.shell import ShellRequest
from minidsh.packages.services.fs import FsRequest
from tests.helpers.world import plug_execution_world


def test_shell_local_provides_service():
    ctx = Context()
    plug_execution_world(ctx)  # subprocess → shell-local → fs-local
    assert ctx.has("shell")


async def test_shell_local_executes():
    ctx = Context()
    plug_execution_world(ctx)
    result = await ctx.shell.execute(ShellRequest(cmd="echo hi"))
    assert "hi" in result.stdout
    assert result.exit_code == 0


async def test_shell_local_captures_nonzero():
    ctx = Context()
    plug_execution_world(ctx)
    result = await ctx.shell.execute(ShellRequest(cmd="echo err >&2; exit 2"))
    assert result.exit_code == 2
    assert "err" in result.stderr


def test_fs_local_provides_service():
    ctx = Context()
    plug_execution_world(ctx)
    assert ctx.has("fs")


async def test_fs_local_reads(tmp_path):
    ctx = Context()
    plug_execution_world(ctx)
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    result = await ctx.fs.execute(FsRequest(path=str(f)))
    assert result.content == "hello"