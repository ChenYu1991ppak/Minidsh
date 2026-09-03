"""infrastructure/tui：交互式终端前端（Textual）。

观察者：只订阅 session/event 渲染会话转录，不新增事件、不改 core 机制。
- ``transcript``：事件 → turn 树（纯视图模型，无 Textual 依赖）
- ``app``：Textual App + 转录/输入/状态三 widget
- ``bridge``：事件桥 + 后台驱动 task
"""
from .transcript import Turn, Block, fold
from .app import TuiApp

__all__ = ["Turn", "Block", "fold", "TuiApp"]