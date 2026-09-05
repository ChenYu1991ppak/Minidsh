/**
 * mini-dsh pi-tui frontend: interactive terminal UI via ACP protocol.
 *
 * Spawns `minidsh --profile acp` as a subprocess, drives one agent session
 * through the ACP JSON-RPC protocol, and renders the conversation with pi-tui.
 *
 * Rendering mirrors the official dsh-tui transcript: a single ordered timeline
 * where tool cards render inline between messages, opportunity dimming, and
 * Ctrl+O cycling tool-card visibility.
 *
 * @module minidsh-pi-tui
 */
import {
  ProcessTerminal,
  TuiMainScreen,
  Spacer,
  Input,
  Key,
  matchesKey,
  truncateToWidth,
  wrapTextWithAnsi,
  type Component,
  type Focusable,
  type TuiInputListenerResult,
  type TuiMouseEvent,
  type TuiMouseEventResult,
} from "@earendil-works/pi-tui";
import { AcpClient, type SessionUpdate } from "./acp-client.js";
import { SessionState, type TranscriptItem } from "./session-state.js";

// ── Constants ──────────────────────────────────────────────────────────────

const PROMPT = "> ";
const MAX_TOOL_RESULT_CHARS = 400;   // 卡片折叠时仅预览前 N 行
const THINKING_MAX_CHARS = 200;       // 思考默认折叠为少量字符
const TOOL_PREVIEW_LINES = 6;

// ── State ──────────────────────────────────────────────────────────────────

const state = new SessionState();
const acp = new AcpClient();

// ── Helpers ────────────────────────────────────────────────────────────────

function dim(text: string): string {
  return `\x1b[2m${text}\x1b[0m`;
}
function bold(text: string): string {
  return `\x1b[1m${text}\x1b[0m`;
}
function accent(text: string): string {
  return `\x1b[95m${text}\x1b[0m`;  // 官方 accent 色（ANSI 95）
}
function success(text: string): string {
  return `\x1b[32m${text}\x1b[0m`;
}
function warning(text: string): string {
  return `\x1b[33m${text}\x1b[0m`;
}
function error(text: string): string {
  return `\x1b[31m${text}\x1b[0m`;
}

function wrapLines(text: string, width: number): string[] {
  if (width <= 0) return text.split("\n");
  const lines: string[] = [];
  for (const line of text.split("\n")) {
    lines.push(...wrapTextWithAnsi(line, width));
  }
  return lines;
}

/** 截取一段文本的前 N 行，折叠时预览用。 */
function previewLines(text: string, maxLines: number, width: number): { lines: string[]; hidden: number } {
  const all = wrapLines(text, width);
  if (all.length <= maxLines) return { lines: all, hidden: 0 };
  return { lines: all.slice(0, maxLines), hidden: all.length - maxLines };
}

// ── Components ─────────────────────────────────────────────────────────────

/** Status bar: model, effort, session id, token usage. */
function statusBar(width: number): string[] {
  const usage = state.usage;
  const pct = usage?.totalTokens && usage?.contextWindow
    ? ` ${Math.round(usage.totalTokens / usage.contextWindow * 100)}%`
    : "";
  const line = ` mini-dsh  ${state.model}(${state.effort})${pct}  ${state.sessionId ?? "connecting..."}`;
  return [truncateToWidth(line, width)];
}

/** 渲染一条 timeline item 的回车行。 */
function renderItem(item: TranscriptItem, width: number): string[] {
  switch (item.type) {
    case "thought": {
      const trimmed = item.text.length > THINKING_MAX_CHARS
        ? item.text.slice(0, THINKING_MAX_CHARS) + "…"
        : item.text;
      return wrapLines(dim(trimmed), width);
    }
    case "user":
      return [bold(accent("## You")), ...wrapLines(item.text, width)];
    case "assistant":
      return [bold(accent("## Assistant")), ...wrapLines(item.text, width)];
    case "tool": {
      const isDone = item.status === "done";
      const glyph = item.status === "in_progress" ? "○" : isDone ? "●" : "●";
      const statusColor = item.status === "in_progress" ? warning : isDone ? success : error;
      const header = truncateToWidth(`${glyph} Tool / ${item.name}`, Math.max(1, width - 2));
      if (item.visibility === "hidden") return [];
      const lines = [statusColor(header)];
      if (item.resultText) {
        if (item.status === "in_progress") return lines;  // pending：仅 header
        if (item.visibility === "collapsed") {
          const { lines: preview, hidden } = previewLines(item.resultText, TOOL_PREVIEW_LINES, width - 2);
          lines.push(...preview.map(l => `  ${dim(l)}`));
          if (hidden > 0) lines.push(dim(`  … +${hidden} lines (Ctrl+O to expand)`));
        } else {
          lines.push(...wrapLines(item.resultText, width - 2).map(l => `  ${dim(l)}`));
        }
      }
      return lines;
    }
  }
}

/** Transcript: single ordered timeline. */
function transcript(width: number): string[] {
  if (width <= 0) width = 80;
  const lines: string[] = [];
  for (const item of state.items) {
    lines.push(...renderItem(item, width));
    lines.push("");  // 每个 item 后空一行（同官方 Spacer 段落间隔）
  }
  if (lines.length === 0) {
    lines.push(truncateToWidth("Welcome to mini-dsh. Type a message to start.", width));
  }
  return lines;
}

/** Input area: editable field with prompt. */
class InputArea implements Component, Focusable {
  focused: boolean = false;
  input: Input;

  constructor() {
    this.input = new Input({ placeholder: "Type a message… (/exit to quit)" });
    this.input.onSubmit = (value: string) => {
      this._handleSubmit(value);
    };
  }

  private _handleSubmit(text: string): void {
    if (!text.trim()) return;
    if (text.trim() === "/exit" || text.trim() === "/quit") {
      acp.stop();
      process.exit(0);
    }
    state.addUserMessage(text.trim());
    acp.sessionPrompt(state.sessionId!, text.trim()).catch((err) => {
      console.error(`[pi-tui] prompt error: ${err}`);
    });
    this.input.setValue("");
  }

  render(width: number): string[] {
    const inputLines = this.input.render(Math.max(1, width - PROMPT.length));
    if (inputLines.length === 0) return [PROMPT];
    return [PROMPT + inputLines[0], ...inputLines.slice(1)];
  }

  handleInput(data: string): void {
    this.input.handleInput(data);
  }

  handleMouse(_event: TuiMouseEvent): TuiMouseEventResult | undefined {
    return undefined;
  }

  invalidate(): void {
    this.input.invalidate();
  }
}

// ── Main ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const cwd = args.find(a => !a.startsWith("-")) ?? process.cwd();
  const extraArgs = args.filter(a => a.startsWith("-"));

  acp.on("exit", (code) => {
    process.exit(code as number);
  });

  await acp.start({ cwd, extraArgs });

  const init = await acp.initialize();
  console.error(`[pi-tui] ACP v${init.protocolVersion} ready`);

  const { sessionId } = await acp.sessionNew();
  state.reset(sessionId);
  console.error(`[pi-tui] session ${sessionId}`);

  const terminal = new ProcessTerminal();
  const tui = new TuiMainScreen(terminal);
  const inputArea = new InputArea();

  acp.onUpdate((update: SessionUpdate) => {
    if (update.sessionId !== state.sessionId) return;
    switch (update.sessionUpdate) {
      case "agent_message_chunk":
        state.addAssistantMessage(update.content?.text ?? "");
        break;
      case "agent_thought_chunk":
        state.addThought(update.content?.text ?? "");
        break;
      case "tool_call":
        if (update.toolCallId) {
          state.setToolCall(update.toolCallId, update.title ?? "tool");
        }
        break;
      case "tool_call_update": {
        const content = (update as { content?: Array<{ content?: string }>; isError?: boolean }).content;
        if (update.toolCallId && content?.[0]?.content) {
          state.setToolResult(update.toolCallId, content[0].content, (update as { isError?: boolean }).isError ?? false);
        }
        break;
      }
    }
    tui.requestRender();
  });

  const statusComponent: Component = { render: statusBar, invalidate: () => {} };
  const transcriptComponent: Component = { render: transcript, invalidate: () => {} };

  tui.addChild(statusComponent);
  const spacer1 = new Spacer();
  spacer1.setLines(1);
  tui.addChild(spacer1);
  tui.addChild(transcriptComponent);
  const spacer2 = new Spacer();
  spacer2.setLines(1);
  tui.addChild(spacer2);
  tui.addChild(inputArea);

  tui.setFocus(inputArea);

  tui.addInputListener((data: string): TuiInputListenerResult => {
    // Ctrl+C 取消当前 turn
    if (matchesKey(data, Key.ctrl("c"))) {
      acp.sessionCancel(state.sessionId!);
      return { consume: true };
    }
    // Ctrl+O 循环工具卡片可见性（hidden → collapsed → expanded）
    if (matchesKey(data, Key.ctrl("o"))) {
      const lastTool = [...state.items].reverse().find(i => i.type === "tool");
      if (lastTool && lastTool.type === "tool") {
        state.cycleToolVisibility(lastTool.callId);
        tui.requestRender();
      }
      return { consume: true };
    }
    return undefined;
  });

  tui.start();
}

main().catch((err) => {
  console.error(`[pi-tui] fatal: ${err}`);
  process.exit(1);
});