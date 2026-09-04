/**
 * mini-dsh pi-tui frontend: interactive terminal UI via ACP protocol.
 *
 * Spawns `minidsh --profile acp` as a subprocess, drives one agent session
 * through the ACP JSON-RPC protocol, and renders the conversation with pi-tui.
 *
 * @module minidsh-pi-tui
 */
import {
  Container,
  ProcessTerminal,
  TuiMainScreen,
  Text,
  Spacer,
  Input,
  Key,
  matchesKey,
  type Component,
  type Focusable,
  type TuiInputListenerResult,
  type TuiMouseEvent,
  type TuiMouseEventResult,
} from "@earendil-works/pi-tui";
import { AcpClient, type SessionUpdate } from "./acp-client.js";
import { SessionState } from "./session-state.js";

// ── Constants ──────────────────────────────────────────────────────────────

const PROMPT = "> ";
const MAX_TOOL_RESULT_CHARS = 500;
const THINKING_MAX_CHARS = 300;

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

function wrapLines(text: string, width: number): string[] {
  if (width <= 0) return text.split("\n");
  const lines: string[] = [];
  for (const line of text.split("\n")) {
    if (line.length <= width) {
      lines.push(line);
      continue;
    }
    let remaining = line;
    while (remaining.length > width) {
      lines.push(remaining.slice(0, width));
      remaining = remaining.slice(width);
    }
    if (remaining) lines.push(remaining);
  }
  return lines;
}

// ── Components ─────────────────────────────────────────────────────────────

/** Status bar: model, effort, session id, token usage. */
function statusBar(_width: number): string[] {
  const usage = state.usage;
  const pct = usage?.totalTokens && usage?.contextWindow
    ? ` ${Math.round(usage.totalTokens / usage.contextWindow * 100)}%`
    : "";
  const line = ` mini-dsh  ${state.model}(${state.effort})${pct}  ${state.sessionId ?? "connecting..."}`;
  return [line];
}

/** Transcript: accumulated entries with tool calls. */
function transcript(width: number): string[] {
  const lines: string[] = [];
  for (const entry of state.entries) {
    if (entry.kind === "thought" && entry.text) {
      const trimmed = entry.text.length > THINKING_MAX_CHARS
        ? entry.text.slice(0, THINKING_MAX_CHARS) + "…"
        : entry.text;
      for (const l of trimmed.split("\n")) {
        lines.push(dim(l));
      }
    } else if (entry.role === "user") {
      lines.push(bold("## You"));
      lines.push(...wrapLines(entry.text, width));
    } else if (entry.role === "assistant" && entry.text) {
      lines.push(bold("## Assistant"));
      lines.push(...wrapLines(entry.text, width));
      lines.push("");
    }
  }
  // Tool calls
  for (const tc of state.toolCalls.values()) {
    const icon = tc.status === "in_progress" ? "⏳" : "✓";
    lines.push(dim(`${icon} ${tc.name}`));
    if (tc.resultText) {
      const truncated = tc.resultText.length > MAX_TOOL_RESULT_CHARS
        ? tc.resultText.slice(0, MAX_TOOL_RESULT_CHARS) + "\n…(truncated)"
        : tc.resultText;
      lines.push(...truncated.split("\n").map(l => `  ${l}`));
    }
  }
  return lines.length > 0 ? lines : ["Welcome to mini-dsh. Type a message to start."];
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
  // Parse CLI args
  const args = process.argv.slice(2);
  const cwd = args.find(a => !a.startsWith("-")) ?? process.cwd();
  const extraArgs = args.filter(a => a.startsWith("-"));

  // Start ACP client
  acp.on("exit", (code) => {
    process.exit(code as number);
  });

  await acp.start({ cwd, extraArgs });

  // Initialize + create session
  const init = await acp.initialize();
  console.error(`[pi-tui] ACP v${init.protocolVersion} ready`);

  const { sessionId } = await acp.sessionNew();
  state.reset(sessionId);
  console.error(`[pi-tui] session ${sessionId}`);

  // ── Build TUI ──

  const terminal = new ProcessTerminal();
  const tui = new TuiMainScreen(terminal);
  const inputArea = new InputArea();

  // Subscribe to updates (needs tui reference for re-render)
  acp.onUpdate((update: SessionUpdate) => {
    if (update.sessionId !== state.sessionId) return;
    switch (update.sessionUpdate) {
      case "agent_message_chunk":
        state.addMessage(update.content?.text ?? "");
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
        const content = (update as { content?: Array<{ content?: string }> }).content;
        if (update.toolCallId && content?.[0]?.content) {
          state.setToolResult(update.toolCallId, content[0].content);
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

  // ── Input handling ──

  tui.addInputListener((data: string): TuiInputListenerResult => {
    // Global hotkeys
    if (matchesKey(data, Key.ctrl("c"))) {
      acp.sessionCancel(state.sessionId!);
      return { consume: true };
    }
    // Forward to input area
    if (inputArea.focused) {
      inputArea.handleInput(data);
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