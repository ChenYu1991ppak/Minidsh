"""M8 验收测试：shell-bash-sandbox（confined bash 经 ctx.sandbox 执行）。"""
from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from minidsh.cordis import Context
from minidsh.infrastructure.config import Config
from minidsh.packages.services.shell import ShellRequest
from minidsh.packages.services.sandbox.providers.bwrap import BwrapSandboxService
from minidsh.packages.services.subprocess.providers.local import LocalSubprocessService
from minidsh.packages.services.shell.providers.sandbox import SandboxShellService

pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap 不可用")


def _ctx_with_sandbox_shell(tmp_path):
    ctx = Context()
    sp = LocalSubprocessService(ctx)
    ctx.provide("subprocess", sp)
    sandbox = BwrapSandboxService(ctx)
    ctx.provide("sandbox", sandbox)
    ctx.provide("root", tmp_path)
    ctx.provide("config", Config())
    shell = SandboxShellService(ctx)
    ctx.provide("shell", shell)
    return ctx, shell, tmp_path


async def test_shell_sandbox_executes_confined(tmp_path):
    ctx, shell, ws = _ctx_with_sandbox_shell(tmp_path)
    result = await shell.execute(ShellRequest(cmd="echo hi"))
    assert "hi" in result.stdout
    assert result.exit_code == 0


async def test_shell_sandbox_nonzero(tmp_path):
    ctx, shell, ws = _ctx_with_sandbox_shell(tmp_path)
    result = await shell.execute(ShellRequest(cmd="echo err >&2; exit 3"))
    assert result.exit_code == 3
    assert "err" in result.stderr


async def test_shell_sandbox_blocks_root_write(tmp_path):
    ctx, shell, ws = _ctx_with_sandbox_shell(tmp_path)
    result = await shell.execute(
        ShellRequest(cmd="touch /etc/_dsh_probe 2>/dev/null && echo wrote || echo blocked")
    )
    assert "blocked" in result.stdout
    assert "wrote" not in result.stdout


async def test_shell_sandbox_timeout(tmp_path):
    ctx, shell, ws = _ctx_with_sandbox_shell(tmp_path)
    result = await shell.execute(ShellRequest(cmd="sleep 5", timeout_seconds=0.2))
    assert result.exit_code == -1
    assert "timed out" in result.stderr