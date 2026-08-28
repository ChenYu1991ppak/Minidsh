"""base 插件：compaction（CompactionEngine，读 ctx.config 阈值）。"""
from __future__ import annotations

from minidsh.capabilities.compaction import CompactionEngine

name = "minidsh.compaction"
inject = ["sessions", "llm", "config"]


def apply(ctx):
    ctx.provide(
        "compaction",
        CompactionEngine(
            ctx,
            context_window=ctx.config.context_window,
            threshold_ratio=ctx.config.compaction_threshold_ratio,
        ),
    )
