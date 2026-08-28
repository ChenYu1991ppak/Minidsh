"""compaction 能力：定义 + 策略。"""
from __future__ import annotations

from .definition import CompactionStrategy, CompactionEngine, measure_messages
from .strategies.prune import PruneStrategy
from .strategies.summarize import SummarizeStrategy

__all__ = ["CompactionStrategy", "CompactionEngine", "PruneStrategy", "SummarizeStrategy", "measure_messages"]
