"""TUI 前端：Textual App + 转录视图 / 输入框 / 状态栏。

参考 Claude Code TUI 的呈现：会话转录按 turn 分块（assistant 流式、tool/subagent
折叠块），底部多行输入，顶栏显示模型 + session id。

分层：本模块只做「渲染 + 输入」，视图模型在 ``transcript.fold``（不 import Textual）；
core 不受影响（只读观察者）。
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Input, Static, Label

from .transcript import Turn, Block, fold
from .bridge import EventMessage

__all__ = ["TuiApp"]


class _Transcript(Static):
    """转录视图：按 turn 渲染成可折叠的 Markdown 近似文本。"""

    def render_turns(self, turns: list[Turn]) -> str:
        lines: list[str] = []
        for turn in turns:
            if turn.kind == "user":
                lines.append(f"### 你\n\n{turn.text}")
            else:
                if turn.thinking:
                    # 思考用 dim（Textual markup 灰/暗色），与回复区分
                    lines.append(f"[dim]{turn.thinking}[/dim]")
                lines.append(f"### assistant\n\n{turn.text}")
                for block in turn.blocks:
                    lines.append(self._render_block(block))
            lines.append("")
        return "\n".join(lines) or "（等待输入…）"

    @staticmethod
    def _render_block(block: Block) -> str:
        state_icon = {"pending": "⏳", "done": "✓", "error": "✗"}.get(block.state, "")
        header = f"<details><summary>{state_icon} {block.header}</summary>\n\n{block.body}\n</details>"
        return header


class TuiApp(App):
    """mini-dsh 交互式 TUI 主界面。

    ``ctx`` + ``agent`` 由 cli 层装配后传入；App 只负责订阅 + 驱动 + 呈现。
    """

    CSS = """
    #transcript { height: 1fr; overflow-y: auto; padding: 1; }
    #status { height: 1; }
    .input-row { height: 3; }
    """

    def __init__(self, ctx, agent):
        super().__init__()
        self.ctx = ctx
        self.agent = agent
        self._events: list = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._drive_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Container(Label("mini-dsh", id="status-label"), id="status")
        yield _Transcript(id="transcript")
        yield Input(placeholder="输入消息…（Ctrl+D 或输入 /exit 退出）", id="input")
        yield Footer()

    # ---------- 生命周期 ----------

    def _find_model(self) -> str:
        cfg = self.ctx.probe("config") if self.ctx.has("config") else None
        return getattr(cfg, "current_model_id", None) or "?"

    def _update_status(self) -> None:
        self.query_one("#status-label", Label).update(
            f"mini-dsh  模型 {self._model}（{self._effort}）  会话 {self.agent.session.id}"
        )

    # ---------- 事件消息 ----------

    def on_event_message(self, message: EventMessage) -> None:
        self._events.append(message.event)
        turns = fold(self._events)
        self._transcript.update(turns and self._transcript.render_turns(turns))
        # 模型/强度切换事件也要刷新状态栏
        if message.event.type == "model-change":
            self._refresh_status()

    async def on_mount(self) -> None:
        from .bridge import subscribe, drive

        self._model = self._find_model()
        self._effort = self._find_effort()
        self._transcript = self.query_one("#transcript", _Transcript)
        self._update_status()
        subscribe(self.ctx, self.post_message)
        self._drive_task = asyncio.create_task(drive(self.agent, self._queue, self.ctx))
        self.set_focus(self.query_one("#input", Input))

    def _refresh_status(self) -> None:
        self._model = self._find_model()
        self._effort = self._find_effort()
        self._update_status()

    def _find_effort(self) -> str:
        return getattr(self.ctx.llm, "reasoning_effort", "medium")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        if text == "/exit":
            await self._quit()
            return
        if text.startswith("/model "):
            await self._switch_model(text[len("/model "):].strip())
            return
        if text.startswith("/thinking "):
            await self._switch_effort(text[len("/thinking "):].strip())
            return
        await self._queue.put(text)

    async def _switch_model(self, model_id: str) -> None:
        spec = self.ctx.config.find(model_id)
        if spec is None:
            self._transcript.update(f"[bold red]未知模型：{model_id}[/bold red]")
            return
        self.ctx.llm.reconfigure(spec)
        self.agent.session.append("model-change", {"model": spec.id})
        self._refresh_status()

    async def _switch_effort(self, level: str) -> None:
        from minidsh.infrastructure.config import REASONING_EFFORTS

        if level not in REASONING_EFFORTS:
            self._transcript.update(f"[bold red]非法档位：{level}[/bold red]（{sorted(REASONING_EFFORTS)}）")
            return
        spec = self.ctx.config.current
        if spec is None:
            return
        spec.reasoning_effort = level
        self.ctx.llm.reconfigure(spec)
        self.agent.session.append("model-change", {"model": self.ctx.llm.model, "effort": level})
        self._refresh_status()

    async def action_quit(self) -> None:
        await self._quit()

    async def _quit(self) -> None:
        from .bridge import shutdown

        await shutdown(self.agent, self._queue, self.ctx)
        self.exit()