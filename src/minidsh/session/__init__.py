"""session 模块：append-only 会话事件流。

事件模型（contract，spec §plan「事件契约」）：会话是一串 ``SessionEvent`` 的
只追加日志，一切可观测性（终端渲染 / 持久化 / 重放 / compaction 触发）都从这条流投影。

本模块分三层：
- ``event.py``：会话事件与事件类型白名单
- ``store.py``：``Session``（追加日志）+ ``SessionStore``（会话注册表服务）
- ``persistence.py`` / ``persistence_jsonl.py`` / ``persistence_sqlite.py``（T4/T5 落地）

[教学简化] 相对 ch03 教学版：不引入 ``turn/start``/``turn/end`` 结构事件——
批刷边界用 ``assistant-message`` 标记（v1 的「一条回复」边界），上下文压缩按
token 压力触发，均不依赖 turn 结构标记。
"""
from __future__ import annotations

from .event import SessionEvent, SessionEventType
from .store import Session, SessionStore

__all__ = ["Session", "SessionEvent", "SessionEventType", "SessionStore"]