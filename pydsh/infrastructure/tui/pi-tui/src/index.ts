/**
 * pydsh pi-tui frontend: interactive terminal UI via ACP protocol.
 *
 * M1: Markdown rendering for assistant messages
 * M2: Slash command system (/model, /help, /exit, /resume, /status)
 * M3: Model selection dialog
 * M4: User question dialog (inline, above input)
 * M5: Session strategy (start=new, /resume to restore)
 *
 * @module pydsh-pi-tui
 */
import {
  ProcessTerminal,
  TuiMainScreen,
  Spacer,
  Input,
  Markdown as PiTuiMarkdown,
  Key,
  matchesKey,
  truncateToWidth,
  wrapTextWithAnsi,
  type Component,
  type Focusable,
  type MarkdownTheme,
  type DefaultTextStyle,
  type TuiInputListenerResult,
  type TuiMouseEvent,
  type TuiMouseEventResult,
} from "@earendil-works/pi-tui";
import { AcpClient, type SessionUpdate } from "./acp-client.js";
import { SessionState, type TranscriptItem, type QuestionData } from "./session-state.js";
import { CommandRegistry } from "./commands.js";

// ── Constants ──────────────────────────────────────────────────────────────

const PROMPT = "> ";
const THINKING_MAX_CHARS = 200;
const TOOL_PREVIEW_LINES = 6;

// ── State ──────────────────────────────────────────────────────────────────

const state = new SessionState();
const acp = new AcpClient();
const commands = new CommandRegistry();

// ── ANSI Helpers ───────────────────────────────────────────────────────────

function dim(text: string): string { return `\x1b[2m${text}\x1b[0m`; }
function bold(text: string): string { return `\x1b[1m${text}\x1b[0m`; }
function accent(text: string): string { return `\x1b[95m${text}\x1b[0m`; }
function success(text: string): string { return `\x1b[32m${text}\x1b[0m`; }
function warning(text: string): string { return `\x1b[33m${text}\x1b[0m`; }
function error(text: string): string { return `\x1b[31m${text}\x1b[0m`; }
function cyan(text: string): string { return `\x1b[36m${text}\x1b[0m`; }
function underline(text: string): string { return `\x1b[4m${text}\x1b[0m`; }

function wrapLines(text: string, width: number): string[] {
  if (width <= 0) return text.split("\n");
  const lines: string[] = [];
  for (const line of text.split("\n")) lines.push(...wrapTextWithAnsi(line, width));
  return lines;
}

function previewLines(text: string, maxLines: number, width: number): { lines: string[]; hidden: number } {
  const all = wrapLines(text, width);
  if (all.length <= maxLines) return { lines: all, hidden: 0 };
  return { lines: all.slice(0, maxLines), hidden: all.length - maxLines };
}

// ── M1: Markdown Theme ─────────────────────────────────────────────────────

const defaultMdStyle: DefaultTextStyle = {};
const mdTheme: MarkdownTheme = {
  heading: bold,
  link: accent,
  linkUrl: dim,
  code: cyan,
  codeBlock: (t: string) => t,
  codeBlockBorder: dim,
  quote: dim,
  quoteBorder: dim,
  hr: dim,
  listBullet: dim,
  bold,
  italic: (t: string) => `\x1b[3m${t}\x1b[0m`,
  strikethrough: dim,
  underline,
};

// ── Components ─────────────────────────────────────────────────────────────

function statusBar(width: number): string[] {
  const usage = state.usage;
  const pct = usage?.used && usage?.size
    ? ` ${Math.round(usage.used / usage.size * 100)}% (${usage.used}/${usage.size})`
    : "";
  const label = state.sessionTitle || state.sessionId || "connecting...";
  const line = ` pydsh  ${state.model}(${state.effort})${pct}  ${label}`;
  return [truncateToWidth(line, width)];
}

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
      return [bold(accent("## Assistant")), ...renderMarkdown(item.text, width)];
    case "tool": {
      const isDone = item.status === "done";
      const glyph = item.status === "in_progress" ? "○" : isDone ? "●" : "●";
      const statusColor = item.status === "in_progress" ? warning : isDone ? success : error;
      const header = truncateToWidth(`${glyph} Tool / ${item.name}`, Math.max(1, width - 2));
      if (item.visibility === "hidden") return [];
      const lines = [statusColor(header)];
      if (item.resultText) {
        if (item.status === "in_progress") return lines;
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

// M1: Markdown renderer
const mdCache = new Map<string, PiTuiMarkdown>();
function renderMarkdown(text: string, width: number): string[] {
  if (width <= 0) width = 80;
  const cacheKey = `${text.slice(0, 200)}:${width}`;
  let md = mdCache.get(cacheKey);
  if (!md) {
    md = new PiTuiMarkdown(text, 0, 0, mdTheme, defaultMdStyle, {});
    mdCache.set(cacheKey, md);
  }
  return md.render(width);
}

function transcript(width: number): string[] {
  if (width <= 0) width = 80;
  const lines: string[] = [];
  for (const item of state.items) {
    lines.push(...renderItem(item, width));
    lines.push("");
  }
  if (lines.length === 0) {
    lines.push(truncateToWidth("Welcome to pydsh. Type a message to start.", width));
  }
  return lines;
}

// ── M4: Question Dialog ────────────────────────────────────────────────────

function questionDialog(width: number): string[] {
  const q = state.pendingQuestion;
  if (!q) return [];
  const lines: string[] = [];
  lines.push(accent(bold(`? ${q.header}: ${q.question}`)));
  lines.push("");
  if (q.multiSelect) {
    lines.push(dim("Space=toggle  Enter=confirm  Esc=cancel"));
  } else {
    lines.push(dim("↑/↓=navigate  Enter=select  Esc=cancel"));
  }
  lines.push("");
  for (let i = 0; i < q.options.length; i++) {
    const opt = q.options[i];
    const marker = q.multiSelect
      ? (q.selectedIndices.includes(i) ? success("[x]") : dim("[ ]"))
      : (i === q.selectedIndex ? accent(">") : " ");
    const label = i === q.selectedIndex ? bold(opt.label) : opt.label;
    const desc = opt.description ? ` — ${dim(opt.description)}` : "";
    lines.push(truncateToWidth(`  ${marker} ${label}${desc}`, width));
  }
  return lines;
}

// ── Input Area ─────────────────────────────────────────────────────────────

class InputArea implements Component, Focusable {
  focused: boolean = false;
  input: Input;
  private _onExit: (() => void) | null = null;

  constructor() {
    this.input = new Input({ placeholder: "Type a message… (/help for commands)" });
    this.input.onSubmit = (value: string) => { this._handleSubmit(value); };
  }

  setOnExit(fn: () => void): void { this._onExit = fn; }

  private _handleSubmit(text: string): void {
    if (!text.trim()) return;
    if (text.trim().startsWith("/")) {
      const handled = commands.dispatch(text.trim());
      if (!handled) {
        state.addUserMessage(text.trim());
        acp.sessionPrompt(state.sessionId!, text.trim()).catch((err) => {
          console.error(`[pi-tui] prompt error: ${err}`);
        });
      }
      this.input.setValue("");
      return;
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

  handleInput(data: string): void { this.input.handleInput(data); }
  handleMouse(_event: TuiMouseEvent): TuiMouseEventResult | undefined { return undefined; }
  invalidate(): void { this.input.invalidate(); }
}

// ── M3: Model Dialog ───────────────────────────────────────────────────────

interface ModelEntry {
  id: string;
  description: string;
  reasoningEffort: string;
}

class ModelDialog {
  private models: ModelEntry[];
  private selectedIndex = 0;
  private filter = "";
  private effortLevels = ["off", "minimal", "low", "medium", "high"];
  private effortIdx = 3;
  visible = true;

  constructor(models: ModelEntry[]) {
    this.models = models;
    const cur = state.effort.toLowerCase();
    const ei = this.effortLevels.indexOf(cur);
    if (ei >= 0) this.effortIdx = ei;
    const si = this.models.findIndex(m => m.id === state.model);
    if (si >= 0) this.selectedIndex = si;
  }

  private get filtered(): ModelEntry[] {
    const f = this.filter.toLowerCase();
    if (!f) return this.models;
    return this.models.filter(m => m.id.toLowerCase().includes(f) || m.description.toLowerCase().includes(f));
  }

  private get selected(): ModelEntry | null {
    const f = this.filtered;
    return f.length ? f[this.selectedIndex] ?? null : null;
  }

  render(width: number): string[] {
    if (!this.visible) return [];
    const maxW = Math.min(76, width - 4);
    const lines: string[] = [];
    lines.push(accent(bold(`┌ Select model ${"─".repeat(Math.max(1, maxW - 14))}`)));
    lines.push(`│ ${dim("Filter:")} ${this.filter}${dim("_")}`);
    lines.push(`│ ${dim("Effort:")} ${bold(this.effortLevels[this.effortIdx])} ${dim("(Shift+Tab)")}`);
    lines.push(`│${"─".repeat(maxW)}`);

    const f = this.filtered;
    if (f.length === 0) {
      lines.push(`│ ${dim("No models match")}`);
    } else {
      const maxVisible = 8;
      const start = Math.max(0, this.selectedIndex - Math.floor(maxVisible / 2));
      const end = Math.min(f.length, start + maxVisible);
      for (let i = start; i < end; i++) {
        const m = f[i], sel = i === this.selectedIndex;
        const marker = sel ? accent(">") : " ";
        const label = sel ? bold(m.id) : m.id;
        const desc = m.description ? ` ${dim(m.description)}` : "";
        lines.push(truncateToWidth(`│ ${marker} ${label} [${m.reasoningEffort}]${desc}`, maxW));
      }
    }
    lines.push(`└${"─".repeat(maxW)}`);
    lines.push(dim("Enter=select  Esc=cancel  Shift+Tab=effort"));
    return lines;
  }

  handleInput(data: string): boolean {
    if (!this.visible) return false;
    if (matchesKey(data, Key.escape)) { this.visible = false; return true; }
    if (matchesKey(data, Key.enter)) {
      const m = this.selected;
      if (m) this._apply(m);
      this.visible = false;
      return true;
    }
    if (matchesKey(data, Key.up)) { this.selectedIndex = Math.max(0, this.selectedIndex - 1); return true; }
    if (matchesKey(data, Key.down)) { this.selectedIndex = Math.min(this.filtered.length - 1, this.selectedIndex + 1); return true; }
    if (matchesKey(data, Key.shift(Key.tab))) { this.effortIdx = (this.effortIdx + 1) % this.effortLevels.length; return true; }
    if (matchesKey(data, Key.backspace)) { this.filter = this.filter.slice(0, -1); this.selectedIndex = 0; return true; }
    if (data.length === 1 && data >= " ") { this.filter += data; this.selectedIndex = 0; return true; }
    return false;
  }

  private async _apply(m: ModelEntry): Promise<void> {
    await acp.sessionSetConfigOption(state.sessionId!, "model", m.id);
    await acp.sessionSetConfigOption(state.sessionId!, "reasoning_effort", this.effortLevels[this.effortIdx]);
    state.model = m.id;
    state.effort = this.effortLevels[this.effortIdx];
  }
}

// ── M5: Resume Dialog ──────────────────────────────────────────────────────

interface SessionEntry { id: string; title?: string; updatedAt?: string; }

class ResumeDialog {
  private sessions: SessionEntry[] = [];
  private selectedIndex = 0;
  visible = false;
  private _onSelect: ((sessionId: string) => void) | null = null;

  async show(): Promise<void> {
    try { this.sessions = await acp.sessionList(); } catch { this.sessions = []; }
    this.selectedIndex = 0;
    this.visible = true;
  }

  setOnSelect(fn: (sessionId: string) => void): void { this._onSelect = fn; }

  render(width: number): string[] {
    if (!this.visible) return [];
    const maxW = Math.min(60, width - 4);
    const lines: string[] = [];
    lines.push(accent(bold(`┌ Resume session ${"─".repeat(Math.max(1, maxW - 17))}`)));
    if (this.sessions.length === 0) {
      lines.push(`│ ${dim("No saved sessions found")}`);
    } else {
      const maxVisible = 8, start = Math.max(0, this.selectedIndex - Math.floor(maxVisible / 2));
      const end = Math.min(this.sessions.length, start + maxVisible);
      for (let i = start; i < end; i++) {
        const s = this.sessions[i], sel = i === this.selectedIndex;
        const marker = sel ? accent(">") : " ";
        const label = s.title || s.id;
        const display = sel ? bold(label) : label;
        const time = s.updatedAt ? ` ${dim(s.updatedAt)}` : "";
        lines.push(truncateToWidth(`│ ${marker} ${display}${time}`, maxW));
      }
    }
    lines.push(`└${"─".repeat(maxW)}`);
    lines.push(dim("Enter=resume  Esc=cancel"));
    return lines;
  }

  handleInput(data: string): boolean {
    if (!this.visible) return false;
    if (matchesKey(data, Key.escape)) { this.visible = false; return true; }
    if (matchesKey(data, Key.enter)) {
      if (this.sessions[this.selectedIndex] && this._onSelect) this._onSelect(this.sessions[this.selectedIndex].id);
      this.visible = false;
      return true;
    }
    if (matchesKey(data, Key.up)) { this.selectedIndex = Math.max(0, this.selectedIndex - 1); return true; }
    if (matchesKey(data, Key.down)) { this.selectedIndex = Math.min(this.sessions.length - 1, this.selectedIndex + 1); return true; }
    return false;
  }
}

// ── M4: Question input handler ─────────────────────────────────────────────

function buildQuestionAnswer(q: QuestionData): string {
  if (q.multiSelect) {
    if (q.selectedIndices.length === 0) return "";
    const labels = q.selectedIndices.map(i => q.options[i].label).join(", ");
    return `${q.header}: ${labels}`;
  }
  if (q.selectedIndex >= 0 && q.selectedIndex < q.options.length) {
    return `${q.header}: ${q.options[q.selectedIndex].label}`;
  }
  return "";
}

function handleQuestionInput(data: string, tui: TuiMainScreen): TuiInputListenerResult {
  const q = state.pendingQuestion;
  if (!q) return { consume: false };

  if (matchesKey(data, Key.escape)) { state.clearQuestion(); tui.requestRender(); return { consume: true }; }
  if (matchesKey(data, Key.enter)) {
    const answer = buildQuestionAnswer(q);
    if (answer) {
      state.items.push({ type: "user", text: answer });
      acp.sessionPrompt(state.sessionId!, answer).catch((err) => { console.error(`[pi-tui] prompt error: ${err}`); });
    }
    state.clearQuestion();
    tui.requestRender();
    return { consume: true };
  }
  if (q.multiSelect && data === " ") {
    const idx = q.selectedIndex;
    if (idx >= 0 && idx < q.options.length) {
      const pos = q.selectedIndices.indexOf(idx);
      if (pos >= 0) q.selectedIndices.splice(pos, 1); else q.selectedIndices.push(idx);
      tui.requestRender();
    }
    return { consume: true };
  }
  if (matchesKey(data, Key.up)) { q.selectedIndex = Math.max(0, q.selectedIndex - 1); tui.requestRender(); return { consume: true }; }
  if (matchesKey(data, Key.down)) { q.selectedIndex = Math.min(q.options.length - 1, q.selectedIndex + 1); tui.requestRender(); return { consume: true }; }
  return { consume: false };
}

// ── Main ───────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const cwd = args.find(a => !a.startsWith("-")) ?? process.cwd();
  const extraArgs = args.filter(a => a.startsWith("-"));

  acp.on("exit", (code) => { process.exit(code as number); });

  await acp.start({ cwd, extraArgs });
  const init = await acp.initialize();
  console.error(`[pi-tui] ACP v${init.protocolVersion} ready`);

  // M5: always start a new session
  const { sessionId } = await acp.sessionNew();
  state.reset(sessionId);
  console.error(`[pi-tui] session ${sessionId} (new)`);

  // Read model config from capabilities
  const models: ModelEntry[] = (init.capabilities?.models as ModelEntry[]) || [];
  if (init.capabilities?.model) {
    state.model = (init.capabilities as Record<string,unknown>).model as string;
  }
  if (init.capabilities?.reasoningEffort) {
    state.effort = (init.capabilities as Record<string,unknown>).reasoningEffort as string;
  }

  const terminal = new ProcessTerminal();
  const tui = new TuiMainScreen(terminal);
  const inputArea = new InputArea();

  let modelDialog: ModelDialog | null = null;
  let resumeDialog: ResumeDialog | null = null;

  // ── M2: Register commands ──────────────────────────────────────────────

  commands.register({
    name: "help", description: "Show available commands and shortcuts",
    handler: () => {
      const help = commands.helpText() + "\n\nShortcuts: Ctrl+C=cancel, Ctrl+O=toggle tool cards";
      state.addUserMessage("/help");
      state.items.push({ type: "assistant", text: help });
      tui.requestRender();
    },
  });

  commands.register({
    name: "model", description: "Open model selection dialog (or /model <id> to switch)",
    handler: async (args: string) => {
      if (args) {
        await acp.sessionSetConfigOption(state.sessionId!, "model", args);
        state.model = args;
        tui.requestRender();
        return;
      }
      if (models.length === 0) {
        state.items.push({ type: "assistant", text: dim("No models configured.") });
        tui.requestRender();
        return;
      }
      modelDialog = new ModelDialog(models);
      tui.requestRender();
    },
  });

  commands.register({
    name: "exit", description: "Exit pydsh gracefully",
    handler: () => { tui.stop(); acp.stop(); process.exit(0); },
  });

  commands.register({
    name: "resume", description: "Open session resume picker",
    handler: async () => {
      resumeDialog = new ResumeDialog();
      resumeDialog.setOnSelect(async (sid: string) => {
        const result = await acp.sessionResume(sid);
        if (result) {
          state.reset(result.sessionId);
          state.model = result.model || "?";
          state.effort = result.effort || "?";
          console.error(`[pi-tui] resumed session ${sid}`);
          tui.requestRender();
        }
      });
      await resumeDialog.show();
      tui.requestRender();
    },
  });

  commands.register({
    name: "status", description: "Show current session info",
    handler: () => {
      const info = [
        `Session: ${state.sessionId}`,
        `Model: ${state.model} (${state.effort})`,
        `Transcript items: ${state.items.length}`,
        `Tokens: ${state.usage?.used ?? "?"}/${state.usage?.size ?? "?"}`,
      ].join("\n");
      state.addUserMessage("/status");
      state.items.push({ type: "assistant", text: info });
      tui.requestRender();
    },
  });

  // ── ACP event handling ─────────────────────────────────────────────────

  acp.onUpdate((update: SessionUpdate) => {
    if (update.sessionId !== state.sessionId) return;
    switch (update.sessionUpdate) {
      case "agent_message_chunk":
        state.addAssistantMessage(update.content?.text ?? "");
        mdCache.clear();
        break;
      case "agent_thought_chunk":
        state.addThought(update.content?.text ?? "");
        break;
      case "tool_call":
        if (update.toolCallId) state.setToolCall(update.toolCallId, update.title ?? "tool");
        break;
      case "tool_call_update": {
        const cu = update as { content?: Array<{ content?: string }>; isError?: boolean };
        if (update.toolCallId && cu.content?.[0]?.content)
          state.setToolResult(update.toolCallId, cu.content[0].content, cu.isError ?? false);
        break;
      }
      case "usage_update":
        state.usage = { used: update.used, size: update.size };
        break;
      case "user_question_update": {
        const qu = update as { questions?: Array<{
          question: string; header: string;
          options: Array<{ label: string; description: string }>;
          multiSelect: boolean;
        }> };
        if (qu.questions?.length) state.setQuestion(qu.questions[0]);
        break;
      }
    }
    tui.requestRender();
  });

  // ── Component tree ──────────────────────────────────────────────────────

  const statusC: Component = { render: statusBar, invalidate: () => {} };
  const transcriptC: Component = { render: transcript, invalidate: () => {} };
  const questionC: Component = { render: questionDialog, invalidate: () => {} };
  const overlayC: Component = {
    render: (width: number) => {
      if (modelDialog?.visible) return modelDialog.render(width);
      if (resumeDialog?.visible) return resumeDialog.render(width);
      return [];
    },
    invalidate: () => {},
  };

  tui.addChild(statusC);
  const s1 = new Spacer(); s1.setLines(1); tui.addChild(s1);
  tui.addChild(transcriptC);
  const s2 = new Spacer(); s2.setLines(1); tui.addChild(s2);
  tui.addChild(questionC);
  tui.addChild(inputArea);
  tui.addChild(overlayC);

  tui.setFocus(inputArea);

  // ── Global input handling ───────────────────────────────────────────────

  tui.addInputListener((data: string): TuiInputListenerResult => {
    if (modelDialog?.visible) {
      if (modelDialog.handleInput(data)) {
        if (!modelDialog.visible) modelDialog = null;
        tui.requestRender();
        return { consume: true };
      }
    }
    if (resumeDialog?.visible) {
      if (resumeDialog.handleInput(data)) {
        if (!resumeDialog.visible) resumeDialog = null;
        tui.requestRender();
        return { consume: true };
      }
    }
    if (state.pendingQuestion) return handleQuestionInput(data, tui);
    if (matchesKey(data, Key.ctrl("c"))) { acp.sessionCancel(state.sessionId!); return { consume: true }; }
    if (matchesKey(data, Key.ctrl("o"))) {
      const lt = [...state.items].reverse().find(i => i.type === "tool");
      if (lt?.type === "tool") { state.cycleToolVisibility(lt.callId); tui.requestRender(); }
      return { consume: true };
    }
    return undefined;
  });

  inputArea.setOnExit(() => { tui.stop(); acp.stop(); process.exit(0); });
  tui.start();
}

main().catch((err) => { console.error(`[pi-tui] fatal: ${err}`); process.exit(1); });