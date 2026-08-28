"""会话事件与事件类型白名单。

源码对应：packages/core/session/src/types.ts:404（SessionEvent）。
事件类型白名单来自 spec/tasks 的「事件契约」（kebab-case + payload）；每个类型
在对应能力模块落地时由该模块产出。

[教学简化] payload 不深冻结（真实版 deepFreeze，index.ts:627）；frozen dataclass
仅冻结事件本身，payload dict 仍可变——调用方契约要求「append 后不改 payload」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["SessionEvent", "SessionEventType"]


class SessionEventType(str, Enum):
    """会话事件类型白名单（契约）。新增类型 = 在此加一个成员（非破坏性）。"""

    USER_MESSAGE = "user-message"          # 用户输入
    ASSISTANT_CHUNK = "assistant-chunk"    # 模型逐段输出
    ASSISTANT_MESSAGE = "assistant-message"  # 模型一轮聚合回复（= flush 边界）
    TOOL_CALL = "tool-call"                # 模型发起工具调用
    TOOL_RESULT = "tool-result"            # 工具执行结果回填
    SKILL_LOADED = "skill-loaded"          # 技能被加载并注入
    SUBAGENT_SPAWN = "subagent-spawn"      # 子 agent 派生
    SUBAGENT_RESULT = "subagent-result"    # 子 agent 返回
    COMPACTION = "compaction"              # 上下文压缩
    ERROR = "error"                        # 错误


_KNOWN_TYPES: frozenset[str] = frozenset(t.value for t in SessionEventType)


def _normalize_type(t: "SessionEventType | str") -> str:
    """把枚举或字符串归一为字符串，未知类型拒绝（白名单）。"""
    value = t.value if isinstance(t, SessionEventType) else t
    if value not in _KNOWN_TYPES:
        raise ValueError(
            f"unknown session event type {value!r}; 已知类型：{sorted(_KNOWN_TYPES)}"
        )
    return value


@dataclass(frozen=True)
class SessionEvent:
    """append-only 事件条目。seq 自增、创建后不可改（FrozenInstanceError）。

    对应 SessionEvent（types.ts:404）；frozen 对应 deepFreeze 的不可变语义。
    """

    session_id: str
    seq: int
    type: str
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        # 校验类型名（构造期即拒绝未知类型，杜绝脏数据进入日志）
        object.__setattr__(self, "type", _normalize_type(self.type))

    def to_dict(self) -> dict:
        """展开为可 JSON 序列化的 dict（持久化序列化用）。"""
        return {
            "session_id": self.session_id,
            "seq": self.seq,
            "type": self.type,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionEvent":
        """从 dict 还原（持久化反序列化用）。"""
        return cls(
            session_id=data["session_id"],
            seq=data["seq"],
            type=data["type"],
            payload=data["payload"],
        )