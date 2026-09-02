"""JSONL 持久化后端。

源码对应：session-persistence-jsonl/src/index.ts:121（materialize :514、appendLines :651、
loadStored :209、commitRepair :436）。

物理形态：``{root}/sessions/{session_id}.jsonl``，一行一个 JSON 事件
（eventLines，format.ts:221）。行内是 ``SessionEvent.to_dict()``。

[教学简化] 真实版目录层级 projectDir/sessionDir/logPath 三级 + encodeSegment 防路径穿越
（format.ts:121-136/:176/:189/:201）；教学版拍平为 ``{root}/sessions/{id}.jsonl``。
真实版用 zstd 压缩（头帧 + 事件帧拼接），教学版写明文。append 用一次
``open(...'a')`` 写整批、每行独立 JSON——既是单后端最简实现，也保证「整行落盘」，
作为 T5 双后端等价测试的 jsonl 基准。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ...session.event import SessionEvent
from ..definition import PersistenceBackend

__all__ = ["JsonlSessionPersistence"]


class JsonlSessionPersistence(PersistenceBackend):
    """JSONL 存储适配器：{root}/sessions/{id}.jsonl，每行一个事件。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"

    def log_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def append_batch(self, session_id: str, events: list[SessionEvent]) -> None:
        if not events:
            return
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_path(session_id)
        lines = "\n".join(json.dumps(e.to_dict(), ensure_ascii=False) for e in events)
        with open(path, "a", encoding="utf-8") as f:
            f.write(lines + "\n")

    def load_stored(self, session_id: str) -> list[SessionEvent] | None:
        path = self.log_path(session_id)
        if not path.exists():
            return None
        events: list[SessionEvent] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                events.append(SessionEvent.from_dict(json.loads(line)))
        return events

    def list(self) -> list[str]:
        if not self.sessions_dir.exists():
            return []
        return [
            p.stem
            for p in sorted(self.sessions_dir.glob("*.jsonl"))
            if p.is_file()
        ]

# ---- provider 插件：提供 ctx.sessionPersistence（jsonl 后端）----
from ..definition import PersistenceCoordinator

name = "minidsh.persistence-jsonl"
inject = ["sessions", "root"]


def apply(ctx):
    backend = JsonlSessionPersistence(ctx.root / ".dsh")
    ctx.provide("sessionPersistence", PersistenceCoordinator(ctx, backend))
    ctx._persistence_backend = backend
