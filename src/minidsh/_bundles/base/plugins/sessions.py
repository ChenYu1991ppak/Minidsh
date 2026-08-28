"""base 插件：sessions（SessionStore）。"""
from __future__ import annotations

from minidsh.capabilities.session import SessionStore

name = "minidsh.sessions"
inject: list[str] = []


def apply(ctx):
    ctx.provide("sessions", SessionStore(ctx))
