"""TUI 前端：Textual App + 转录视图 / 输入框 / 状态栏。

参考 Claude Code TUI 的呈现：会话转录按 turn 分块（assistant 流式、tool/subagent
折叠块），底部多行输入，顶栏显示模型 + session id。

分层：本模块只做「渲染 + 输入」，视图模型在 ``transcript.fold``（不 import Textual）；
core 不受影响（只读观察者）。
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Input, Static, Label
from rich.text import Text

from .transcript import Turn, Block, fold
from .bridge import EventMessage

__all__ = ["TuiApp"]


class _Transcript(Static):
    """转录视图：按 turn 渲染。返回 rich ``Text``（思考段带 dim 样式，正文/工具结果
    一律当纯文本，杜绝 markup 误解析 payload 里的 ``[...]``）。"""

    def render_turns(self, turns: list[Turn]) -> Text:
        text = Text()
        for turn in turns:
            if turn.kind == "user":
                text.append("### 你\n\n", style="bold")
                text.append(turn.text)
                text.append("\n")
            else:
                if turn.thinking:
                    text.append(turn.thinking + "\n", style="dim italic")
                text.append("### assistant\n\n", style="bold")
                text.append(turn.text)
                text.append("\n")
                for block in turn.blocks:
                    self._append_block(text, block)
            text.append("\n")
        return text or Text("（等待输入…）")

    @staticmethod
    def _append_block(text: Text, block: Block) -> None:
        state_icon = {"pending": "⏳", "done": "✓", "error": "✗"}.get(block.state, "")
        text.append(f"{state_icon} {block.header}\n", style="dim")
        if block.body:
            text.append(f"    {block.body}\n")


class TuiApp(App):
    """mini-dsh 交互式 TUI 主界面。

    ``ctx`` + ``agent`` 由 cli 层装配后传入；App 只负责订阅 + 驱动 + 呈现。
    """

    CSS = """
    #transcript-scroll { height: 1fr; padding: 1; }
    #transcript { height: auto; }
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
        self._refresh_pending: bool = False

    def compose(self) -> ComposeResult:
        yield Container(Label("mini-dsh", id="status-label"), id="status")
        with VerticalScroll(id="transcript-scroll"):
            yield _Transcript(id="transcript")
        yield Input(placeholder="输入消息…（Ctrl+D 或输入 /exit 退出）", id="input")
        yield Footer()

    # ---------- 生命周期 ----------

    def _find_model(self) -> str:
        # 以 llm 当前实际模型为准（reconfigure 后即时反映，含 /model 切换）
        if self.ctx.has("llm"):
            return getattr(self.ctx.llm, "model", "?") or "?"
        cfg = self.ctx.probe("config") if self.ctx.has("config") else None
        return getattr(cfg, "current_model_id", None) or "?"

    def _update_status(self) -> None:
        self.query_one("#status-label", Label).update(
            f"mini-dsh  模型 {self._model}（{self._effort}）  会话 {self.agent.session.id}"
        )

    # ---------- 事件消息 ----------

    def on_event_message(self, message: EventMessage) -> None:
        self._events.append(message.event)
        # 刷新合并到下一帧渲染：事件可能在高频到达（流式 chunk），逐条 update 会
        # 反复重算整棵树 + 反复向 App 提交重绘，压垮事件循环，表现为「第二轮卡死」。
        if message.event.type == "model-change":
            self._refresh_status()
        if not getattr(self, "_refresh_pending", False):
            self._refresh_pending = True
            self.call_after_refresh(self._flush_transcript)

    async def on_mount(self) -> None:
        from .bridge import subscribe, drive

        self._model = self._find_model()
        self._effort = self._find_effort()
        self._transcript = self.query_one("#transcript", _Transcript)
        # 恢复会话：历史事件经 Session.adopt 装入但不重广播，这里显式 seed 进视图，
        # 否则重启后转录空白（消息历史其实已接上）。
        self._events = list(self.agent.session.events())
        self._update_status()
        subscribe(self.ctx, self.post_message)
        self._drive_task = asyncio.create_task(drive(self.agent, self._queue, self.ctx))
        self.set_focus(self.query_one("#input", Input))
        # 有历史就立即渲染（不等新事件到达）
        if self._events:
            self._flush_transcript()

    def _refresh_status(self) -> None:
        self._model = self._find_model()
        self._effort = self._find_effort()
        self._update_status()

    def _find_effort(self) -> str:
        return getattr(self.ctx.llm, "reasoning_effort", "medium")

    def _flush_transcript(self) -> None:
        """在下一帧一次性重算 + 重绘转录（合并高频事件到达的多次刷新）。"""
        self._refresh_pending = False
        turns = fold(self._events)
        self._transcript.update(self._transcript.render_turns(turns))
        # 内容增长时随输出下移到最底（force=True 覆盖用户暂停滚动）
        scroll = self.query_one("#transcript-scroll", VerticalScroll)
        scroll.scroll_end(animate=False, force=True)

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
        if text == "/new":
            await self._new_session()
            return
        await self._queue.put(text)

    async def _new_session(self) -> None:
        """新建会话：结束当前会话上下文，让用户开新会话。

        退出当前 App（bridge 驱动 flush 当前会话落盘），让上层进程重启或重新 create。
        这里采用「标记 + 退出」语义：flush 后 exit，下次启动默认接最新会话（就是刚 flush 的）。
        """
        from .bridge import shutdown

        # 先 flush 当前会话，再投递退出。新会话由用户下次 minidsh（默认接最新）承担。
        await shutdown(self.agent, self._queue, self.ctx)
        self.exit()

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