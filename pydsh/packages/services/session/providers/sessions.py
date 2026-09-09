"""base 插件：sessions（SessionStore）。"""
from __future__ import annotations

from pydsh.packages.services.session import SessionStore

name = "pydsh.sessions"
inject: list[str] = []


def apply(ctx):
    ctx.provide("sessions", SessionStore(ctx))
