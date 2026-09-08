"""base 插件：sessions（SessionStore）。"""
from __future__ import annotations

from minidsh.packages.services.session import SessionStore

name = "minidsh.sessions"
inject: list[str] = []


def apply(ctx):
    ctx.provide("sessions", SessionStore(ctx))
