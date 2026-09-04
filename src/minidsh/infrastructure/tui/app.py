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
from .bridge import EventMessage, NewSessionMessage
from .commands import Command, CommandRegistry

__all__ = ["TuiApp"]


def _meta_summary(meta: dict) -> str:
    """把结构化展示元数据压成一行摘要（M5）。

    识别 web_fetch（url/statusCode/truncated）与 web_search（sources 数/truncated）；
    其余返回空串（回退 header/body 文本）。纯展示层，不解析模型文本。
    """
    if not isinstance(meta, dict):
        return ""
    if "url" in meta and "statusCode" in meta:
        line = f"Fetched {meta['url']} (HTTP {meta['statusCode']})"
        if meta.get("truncated"):
            line += " · truncated"
        return line
    if "sources" in meta:
        n = len(meta.get("sources") or [])
        line = f"{n} source(s)"
        if meta.get("truncated"):
            line += " · truncated"
        return line
    return ""


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
        # M5：有结构化展示元数据时，追加一行摘要（如 web_fetch 的 url/status/截断）
        if block.meta:
            meta_line = _meta_summary(block.meta)
            if meta_line:
                text.append(f"    {meta_line}\n", style="dim italic")
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
        self._agent_latest = False
        self._agent_ref = [agent]     # callable 视角的当前 agent（drive 经它跟随切换）
        self._commands = CommandRegistry()
        # 四个内置命令注册进注册表（对齐官方 interaction/commands 的命令面）
        self._commands.register(Command(
            "exit", "退出 minidsh", lambda app, arg: app._quit()))
        self._commands.register(Command(
            "model", "切换模型（/model <id>）", lambda app, arg: app._switch_model(arg)))
        self._commands.register(Command(
            "thinking", "切换思考档位（/thinking <level>）", lambda app, arg: app._switch_effort(arg)))
        self._commands.register(Command(
            "new", "新建会话", lambda app, arg: app._new_session()))
        # M6：人类审批应答状态（无待审批时 _approval_future 为 None）
        self._approval_future: asyncio.Future | None = None

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
        # M7：token 用量 + session title（有 title 优先，无则回退 session id）
        tokens = self._token_display()
        title_or_id = self.agent.session.title or self.agent.session.id
        self.query_one("#status-label", Label).update(
            f"mini-dsh  模型 {self._model}（{self._effort}）  {tokens}  会话 {title_or_id}"
        )

    def _token_display(self) -> str:
        """（M7）从 tokenMeter 读当前 token 用量；不可用时回退 '?'."""
        try:
            if self.ctx.has("tokenMeter"):
                measurement = self.ctx.tokenMeter.measure(self.agent.session)
                return f"{measurement.surface_tokens} tokens"
        except Exception:
            pass
        return "? tokens"

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
        self._drive_task = asyncio.create_task(
            drive(lambda: self._agent_ref[0], self._queue, self.ctx)
        )
        self.set_focus(self.query_one("#input", Input))
        # M6：装配人类审批应答者（若 approval 服务已提供）
        if self.ctx.has("approval"):
            self.ctx.approval.register_answerer(self._human_approval)
        # 有历史就立即渲染（不等新事件到达）
        if self._events:
            self._flush_transcript()

    # ---------- M6 人类审批应答者 ----------

    async def _human_approval(self, req, next_):
        """TUI 人类审批应答者（对齐官方 user-approval 的 UI 应答者）。

        渲染审批提示 → 等待用户按键（y=允许 / n=拒绝 / esc=取消）→ 返回 outcome。
        ``await`` 期间不阻塞事件循环（Future 由按键 handler 置位）。无待审批时
        返回 ``None`` 委托下一应答者（此处即 fail-closed ``unavailable``）。
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._approval_future = future
        # 审批期间禁用输入框，让 y/n/esc 冒泡到 App（而非被 Input 吞掉）
        inp = self.query_one("#input", Input)
        inp.disabled = True
        reason = getattr(req, "reason", None) or ""
        tool_name = getattr(req, "tool_name", "?")
        from .transcript import bound_body
        prompt = (f"⚠ 审批请求：{tool_name}"
                  + (f" — {bound_body(reason, 200)}" if reason else "")
                  + "  [y 允许 / n 拒绝 / esc 取消]")
        self.query_one("#status-label", Label).update(prompt)
        try:
            outcome = await future
            return outcome
        finally:
            self._approval_future = None
            # 复位输入框 + 状态栏；teardown 期间 widget 可能已卸载，防御式忽略
            try:
                inp.disabled = False
                self._refresh_status()
                self.set_focus(inp)
            except Exception:
                pass

    def _resolve_approval(self, outcome: str) -> None:
        """按键置位待审批 Future（无待审批时忽略）。"""
        if self._approval_future is not None and not self._approval_future.done():
            self._approval_future.set_result(outcome)

    def key_y(self) -> None:
        self._resolve_approval("allowed-once")

    def key_n(self) -> None:
        self._resolve_approval("rejected")

    def key_escape(self) -> None:
        self._resolve_approval("cancelled")

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
        # 只在用户本就停在底部时才跟随下移——用户上滚回看时不被强制打断。
        scroll = self.query_one("#transcript-scroll", VerticalScroll)
        if scroll.scroll_y >= scroll.max_scroll_y - 1:
            scroll.scroll_end(animate=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.clear()
        if not text:
            return
        # 斜杠命令经注册表分发；未匹配的命令名降级为普通用户消息（对齐官方）
        if await self._commands.dispatch(self, text):
            return
        await self._queue.put(text)

    async def _new_session(self) -> None:
        """新建会话：切换到一个新 agent（进程保持，不退出）。

        经 NewSessionMessage 在 App 主循环里安全切换——不能直接在输入 handler 里
        换 self.agent（驱动 task 正在消费队列，synchro 需回到 app 消息循环）。
        """
        from .bridge import NewSessionMessage

        self.post_message(NewSessionMessage())

    def on_new_session_message(self, message) -> None:
        loop = self.ctx.probe("agent_loop")
        new_agent = loop.create()          # 新 Session（session-000N 递增）
        self._agent_ref[0] = new_agent     # 驱动 task 下次 send 跟随新 agent
        self.agent = new_agent
        self._events = []                  # 清空转录
        self._transcript.update(Text("（新会话）"))
        self._refresh_status()

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