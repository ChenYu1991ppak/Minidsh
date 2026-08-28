"""mini-dsh —— 最小化 DeepSeek Harness。

忠实复刻 DeepSeek Harness（dsh）的工程骨架：以 Cordis「一切皆插件」容器为内核，
串起 agent-loop / tools / skills / subagent / session 事件流 / LLM 适配 / compaction，
做到可运行、可观测、可追溯，并为未来扩展留 seam。

参考：本仓库内 `deepseek-harness-anatomy/`（只读）；机制名与其逐章对齐。
"""
from __future__ import annotations

# 版本号是「单一真相源」：pyproject.toml 通过 ``[tool.hatch.version] path`` 读它，
# 无需在两处手动同步（见 pyproject.toml）。升级版本只改这里。
__version__ = "0.1.0"

__all__ = ["__version__"]