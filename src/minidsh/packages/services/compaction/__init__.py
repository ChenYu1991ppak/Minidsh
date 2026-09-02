"""compaction 能力：token 压力下的上下文压缩（定义 + 策略）。

``definition.py`` 是 CompactionStrategy 接口 + CompactionEngine 服务；
``strategies/`` 是策略实现（prune = 无模型裁剪，summarize = LLM 摘要）。
策略是「内部配置项」，不是 Service provider，故用 strategies/ 而非 providers/。
"""
from __future__ import annotations

from .definition import CompactionStrategy, CompactionEngine, measure_messages
from .strategies.prune import PruneStrategy
from .strategies.summarize import SummarizeStrategy

__all__ = ["CompactionStrategy", "CompactionEngine", "PruneStrategy", "SummarizeStrategy", "measure_messages"]
