"""base 插件：persistence（按 ctx.config.storage 选 backend，写 ctx.root/.dsh）。"""
from __future__ import annotations

from minidsh.capabilities.session.persistence import PersistenceCoordinator
from minidsh.capabilities.session.providers.jsonl import JsonlSessionPersistence
from minidsh.capabilities.session.providers.sqlite import SqliteSessionPersistence

name = "minidsh.persistence"
inject = ["sessions", "config", "root"]


def apply(ctx):
    storage_root = ctx.root / ".dsh"
    if ctx.config.storage == "sqlite":
        backend = SqliteSessionPersistence(storage_root)
    else:
        backend = JsonlSessionPersistence(storage_root)
    ctx.provide("sessionPersistence", PersistenceCoordinator(ctx, backend))
    ctx._persistence_backend = backend
