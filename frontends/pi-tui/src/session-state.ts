/**
 * Session state: a single ordered transcript timeline plus turn/model metadata.
 *
 * The frontend owns a local projection of the ACP session. The transcript is a
 * flat, chronologically-ordered list of items (thought / user / assistant /
 * tool) — mirroring the append-origin session log — so tool cards render inline
 * between the messages that bracket them, not dumped at the bottom.
 *
 * @module minidsh-pi-tui/session-state
 */

export type ToolVisibility = "hidden" | "collapsed" | "expanded";

export type TranscriptItem =
  | { type: "thought"; text: string }
  | { type: "user"; text: string }
  | { type: "assistant"; text: string }
  | {
      type: "tool";
      callId: string;
      name: string;
      status: "in_progress" | "done" | "error";
      resultText?: string;
      visibility: ToolVisibility;
    };

export class SessionState {
  sessionId: string | null = null;
  model = "?";
  effort = "?";
  /** Single ordered timeline: thoughts, messages, and tool cards interleaved by arrival. */
  items: TranscriptItem[] = [];
  /** Latest usage update (token budget percent). */
  usage: { totalTokens?: number; contextWindow?: number } | null = null;

  reset(sessionId: string): void {
    this.sessionId = sessionId;
    this.items = [];
  }

  /** Append to the tail item when it is an assistant thought; else push a new one. */
  addThought(text: string): void {
    if (!text) return;
    const last = this.items[this.items.length - 1];
    if (last?.type === "thought") {
      last.text += text;
    } else {
      this.items.push({ type: "thought", text });
    }
  }

  /** Append to the tail item when it is assistant text; else push a new one. */
  addAssistantMessage(text: string): void {
    if (!text) return;
    const last = this.items[this.items.length - 1];
    if (last?.type === "assistant") {
      last.text += text;
    } else {
      this.items.push({ type: "assistant", text });
    }
  }

  addUserMessage(text: string): void {
    this.items.push({ type: "user", text });
  }

  /** Record a tool call as an inline card in its chronological position. */
  setToolCall(callId: string, name: string): void {
    this.items.push({ type: "tool", callId, name, status: "in_progress", visibility: "collapsed" });
  }

  /** Attach the result to the tool card with the matching call id. */
  setToolResult(callId: string, text: string, isError: boolean): void {
    const item = this.items.find(i => i.type === "tool" && i.callId === callId);
    if (!item || item.type !== "tool") return;
    item.status = isError ? "error" : "done";
    item.resultText = text;
  }

  /** Cycle one tool card's visibility (hidden → collapsed → expanded → hidden). */
  cycleToolVisibility(callId: string): void {
    const item = this.items.find(i => i.type === "tool" && i.callId === callId);
    if (!item || item.type !== "tool") return;
    item.visibility = item.visibility === "hidden" ? "collapsed"
      : item.visibility === "collapsed" ? "expanded"
        : "hidden";
  }
}