/**
 * Session state: accumulated transcript and turn/model metadata.
 *
 * The frontend owns a local projection of the ACP session, mirroring what the
 * official dsh-tui kept in `agent.session`. It grows from ACP session/update
 * notifications and stays agnostic of the backend's internal event model.
 *
 * @module minidsh-pi-tui/session-state
 */

export interface TranscriptEntry {
  kind: "thought" | "message";
  role: "user" | "assistant";
  text: string;
}

export interface ToolCallEntry {
  callId: string;
  name: string;
  status: "in_progress" | "done";
  title?: string;
  resultText?: string;
}

export class SessionState {
  sessionId: string | null = null;
  model = "?";
  effort = "?";
  entries: TranscriptEntry[] = [];
  toolCalls = new Map<string, ToolCallEntry>();
  /** Latest usage update (token budget percent). */
  usage: { totalTokens?: number; contextWindow?: number } | null = null;

  reset(sessionId: string): void {
    this.sessionId = sessionId;
    this.entries = [];
    this.toolCalls.clear();
  }

  addThought(text: string): void {
    if (!text) return;
    const last = this.entries[this.entries.length - 1];
    if (last && last.kind === "thought" && last.role === "assistant") {
      last.text += text;
    } else {
      this.entries.push({ kind: "thought", role: "assistant", text });
    }
  }

  addMessage(text: string): void {
    if (!text) return;
    const last = this.entries[this.entries.length - 1];
    if (last && last.kind === "message" && last.role === "assistant") {
      last.text += text;
    } else {
      this.entries.push({ kind: "message", role: "assistant", text });
    }
  }

  addUserMessage(text: string): void {
    this.entries.push({ kind: "message", role: "user", text });
  }

  setToolCall(callId: string, name: string): void {
    this.toolCalls.set(callId, { callId, name, status: "in_progress" });
  }

  setToolResult(callId: string, text: string): void {
    const tc = this.toolCalls.get(callId);
    if (tc) {
      tc.status = "done";
      // Truncate long tool results for display (mirrors output-retention)
      tc.resultText = text.length > 500 ? text.slice(0, 500) + "\n…(truncated)" : text;
    }
  }
}