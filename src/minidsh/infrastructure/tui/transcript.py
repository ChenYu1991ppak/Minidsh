"""transcript：SessionEvent 流 → turn 树（纯视图模型，不依赖 Textual）。

参考 Claude Code TUI 的会话转录：一轮对话（turn）由 user / assistant / tool 三类组成；
tool-call 与 tool-result 折叠成一个 Block，subagent spawn/result 折叠成嵌套 Block。

fold 是**幂等快照**（传入当前事件列表，重算整棵 turn 树）——TUI 每次事件到达就重载
视图，简单且正确；与「投影折叠」同一读法（framework drives, view folds）。

[教学简化] 不做 Markdown 完整渲染、不做 thinking/引用折叠；只做「归类 + 折叠块」。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Turn", "Block", "fold", "EMPTY_TURNS", "bound_body", "MAX_BLOCK_BODY_CHARS"]

# 转录层有界渲染：单块正文上限。截断是**纯展示层**决策（只读视图模型，不回改
# session 里的完整事件，模型侧仍拿到完整 result）。session-0002 的 web_fetch 抓到
# 79KB HTML 直接把 Rich Text 排版压到 O(n²) 卡死，此上限在有界展示处兜底。
MAX_BLOCK_BODY_CHARS = 2000


def bound_body(body: str, max_chars: int = MAX_BLOCK_BODY_CHARS) -> str:
    """有界正文：超限截断为前缀 + 截断标记；否则原样返回。

    纯函数、无状态；M6 审批卡片也复用此函数（reason 有界展示）。
    """
    if body is None:
        return ""
    if len(body) <= max_chars:
        return body
    return f"{body[:max_chars]}\n…(截断，原文 {len(body)} 字符)"


@dataclass
class Block:
    """turn 内的一个可折叠块：工具调用 / 子代理 / 压缩 / 技能加载 / 错误。

    - ``header``：折叠标题（name + 摘要一行）；
    - ``body``：展开正文（工具结果 / 子代理摘要）；
    - ``state``：``pending``（只看到 tool-call，等 tool-result）/ ``done`` / ``error``；
    - ``meta``：（M5 双通道）结构化展示元数据（工具 ``presentation_meta`` 产出，随
      tool-result 事件落盘）。有则 UI 可渲染结构化卡片，无则回退 ``header``/``body`` 文本。
    """

    kind: str                 # "tool" | "subagent" | "compaction" | "skill" | "error"
    header: str
    body: str = ""
    state: str = "done"       # pending | done | error
    meta: dict | None = None  # M5：结构化展示元数据（可选）


@dataclass
class Turn:
    """一轮对话。kind = user | assistant；assistant 有流式思考 + 回复 + 子块。"""

    kind: str                 # "user" | "assistant"
    text: str = ""            # user 消息正文 / assistant 流式累积回复文本
    thinking: str = ""        # assistant 思考累积（reasoning-chunk）
    blocks: list[Block] = field(default_factory=list)


KNOWN_TURNS = ("user", "assistant")


def _new_turn(kind: str, turns: list[Turn]) -> Turn:
    turn = Turn(kind=kind)
    turns.append(turn)
    return turn


def _side_note_turn(current, turns) -> Turn:
    """旁注块（compaction/skill/error/孤立 subagent）只落在 assistant turn 上。

    当前 current 是 assistant 就用它；否则新建一个 assistant turn（不入 user turn）。
    """
    if current is None or current.kind != "assistant":
        current = _new_turn("assistant", turns)
    return current


def fold(events) -> list[Turn]:
    """事件流 → turn 列表。events 为 SessionEvent 序列（按 seq 有序）。"""
    turns: list[Turn] = []
    current: Turn | None = None
    # 工具调用暂存区：call_id → (block, 所在 turn)；subagent 按 spawn 计数配对
    pending_tools: dict[str, Block] = {}
    pending_subagent: Block | None = None
    pending_approvals: dict[str, Block] = {}   # M6：approval id → 审批块

    def collect_chunk(current: Turn, event) -> None:
        if current is not None and current.kind == "assistant":
            current.text += event.payload.get("text", "")

    for event in events:
        etype = event.type
        payload = event.payload

        if etype == "user-message":
            current = _new_turn("user", turns)
            current.text = payload.get("text", "")

        elif etype == "assistant-chunk":
            if current is None or current.kind != "assistant":
                current = _new_turn("assistant", turns)
            current.text += payload.get("text", "")

        elif etype == "reasoning-chunk":
            if current is None or current.kind != "assistant":
                current = _new_turn("assistant", turns)
            current.thinking += payload.get("text", "")

        elif etype == "assistant-message":
            # flush 边界：锁定该 assistant turn（文本以 message content 为准）
            if current is None or current.kind != "assistant":
                current = _new_turn("assistant", turns)
            current.text = payload.get("content", current.text)

        elif etype == "tool-call":
            args = payload.get("arguments", "")
            if not isinstance(args, str):
                args = _compact(args)
            block = Block(
                kind="tool",
                header=f"⌘ {payload.get('name', 'tool')} {args}".strip(),
                state="pending",
            )
            pending_tools[payload.get("name", block.header)] = block
            if current is None or current.kind != "assistant":
                current = _new_turn("assistant", turns)
            current.blocks.append(block)

        elif etype == "tool-result":
            name = payload.get("name", "")
            block = _pop_by_name(pending_tools, name)
            if block is not None:
                block.body = bound_body(payload.get("result", ""))
                block.state = "error" if payload.get("is_error") else "done"
                block.meta = payload.get("meta")   # M5：结构化展示元数据（可选）
            else:
                # 孤立 tool-result（无 tool-call 前导）→ 当作独立旁注
                current = _side_note_turn(current, turns)
                current.blocks.append(Block(
                    kind="tool",
                    header=f"⌘ {name}",
                    body=bound_body(payload.get("result", "")),
                    state="error" if payload.get("is_error") else "done",
                    meta=payload.get("meta"),
                ))

        elif etype == "subagent-spawn":
            pending_subagent = Block(
                kind="subagent",
                header=f"⏵ {payload.get('agent', 'subagent')}",
                body=payload.get("task", ""),
                state="pending",
            )
            current = _side_note_turn(current, turns)
            current.blocks.append(pending_subagent)

        elif etype == "subagent-result":
            if pending_subagent is not None:
                pending_subagent.state = "done"
                pending_subagent.body = bound_body(payload.get("result", ""))
                pending_subagent = None
            else:
                current = _side_note_turn(current, turns)
                current.blocks.append(Block(
                    kind="subagent",
                    header=f"⏵ {payload.get('agent', 'subagent')}",
                    body=bound_body(payload.get("result", "")),
                ))

        elif etype == "compaction":
            current = _side_note_turn(current, turns)
            current.blocks.append(Block(
                kind="compaction",
                header="≡ 上下文压缩",
                body=bound_body(str(payload)),
            ))

        elif etype == "skill-loaded":
            current = _side_note_turn(current, turns)
            current.blocks.append(Block(
                kind="skill",
                header=f"✦ 加载技能 {payload.get('name', '')}",
            ))

        elif etype == "error":
            current = _side_note_turn(current, turns)
            current.blocks.append(Block(
                kind="error",
                header=f"✗ {payload.get('message', 'error')}",
                state="error",
            ))

        elif etype == "approval/asked":
            # M6：审批请求旁注块（按 id 暂存，等 approval/decided 配对）
            block = Block(
                kind="approval",
                header=f"⚠ 审批 {payload.get('tool_name', '?')}"
                       + (f" — {payload.get('reason')}" if payload.get("reason") else ""),
                state="pending",
            )
            pending_approvals[payload.get("id")] = block
            current = _side_note_turn(current, turns)
            current.blocks.append(block)

        elif etype == "approval/decided":
            block = pending_approvals.pop(payload.get("id"), None)
            outcome = payload.get("outcome", "")
            if block is not None:
                block.state = "done" if outcome == "allowed-once" else "error"
                block.body = bound_body(f"结果：{outcome}")
            else:
                # 孤立 decided（无对应 asked）→ 独立旁注
                current = _side_note_turn(current, turns)
                current.blocks.append(Block(
                    kind="approval",
                    header=f"⚠ 审批结果：{outcome}",
                    body=bound_body(f"结果：{outcome}"),
                    state="done" if outcome == "allowed-once" else "error",
                ))

        # 未知事件类型忽略（白名单外不会发生，防御式跳过）

    return turns


def _pop_by_name(pending: dict[str, Block], name: str) -> Block | None:
    """按名字摘取一个 pending tool block（多工具按序配对，简单可靠）。"""
    if pending:
        key = next(iter(pending))
        return pending.pop(key)
    return None


def _compact(value) -> str:
    """把 dict/list 压成单行摘要（避免 header 撑破行）。"""
    import json

    return json.dumps(value, ensure_ascii=False)


EMPTY_TURNS: list[Turn] = []