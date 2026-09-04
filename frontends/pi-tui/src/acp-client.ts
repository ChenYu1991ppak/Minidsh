/**
 * ACP JSON-RPC client for pi-tui frontend.
 *
 * Spawns `minidsh --profile acp` as a subprocess and communicates via
 * JSON-RPC 2.0 over ndjson on stdin/stdout. Handles response routing
 * (by id) and async notification dispatch.
 *
 * @module minidsh-pi-tui/acp-client
 */
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import { EventEmitter } from "node:events";

export interface AcpClientOptions {
  /** Path to minidsh binary (default: "minidsh") */
  bin?: string;
  /** Working directory (default: process.cwd()) */
  cwd?: string;
  /** Extra args after --profile acp */
  extraArgs?: string[];
}

export interface InitializeResult {
  protocolVersion: number;
  capabilities: Record<string, unknown>;
}

export interface SessionNewResult {
  sessionId: string;
}

export interface PromptResult {
  stopReason: string;
}

export interface SessionUpdate {
  sessionId: string;
  sessionUpdate: string;
  content?: { type: string; text: string };
  toolCallId?: string;
  title?: string;
  kind?: string;
  status?: string;
}

export type NotificationHandler = (method: string, params: Record<string, unknown>) => void;

export class AcpClient extends EventEmitter {
  private proc: ChildProcess | null = null;
  private nextId = 1;
  private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();

  constructor(private options: AcpClientOptions = {}) {
    super();
  }

  /** Start the ACP subprocess and wait for it to be ready. */
  async start(overrides?: Partial<AcpClientOptions>): Promise<void> {
    const opts: AcpClientOptions = { ...this.options, ...overrides };
    // MINIDSH_BIN 由 launcher（minidsh --profile tui）注入；否则默认 "minidsh"
    const bin = process.env.MINIDSH_BIN ?? opts.bin ?? "minidsh";
    // ACP 后端 profile：默认 acp，可用 MINIDSH_ACP_PROFILE 覆盖（如 acp-fake 免 API key）
    const profile = process.env.MINIDSH_ACP_PROFILE ?? "acp";
    const args = ["--profile", profile, ...(opts.extraArgs ?? [])];
    const cwd = opts.cwd ?? process.cwd();

    this.proc = spawn(bin, args, {
      cwd,
      stdio: ["pipe", "pipe", "inherit"], // stderr → inherit for logging
    });

    this.proc.on("exit", (code) => {
      this.emit("exit", code);
      // Reject all pending requests
      for (const [, p] of this.pending) {
        p.reject(new Error(`ACP server exited with code ${code}`));
      }
      this.pending.clear();
    });

    // Read stdout line by line (ndjson)
    const rl = createInterface({ input: this.proc.stdout!, crlfDelay: Infinity });
    rl.on("line", (line: string) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const obj = JSON.parse(trimmed);
        this._handleMessage(obj);
      } catch {
        // Ignore parse errors
      }
    });
  }

  private _handleMessage(obj: Record<string, unknown>): void {
    if (obj.method !== undefined) {
      // Notification
      this.emit("notification", obj.method, obj.params ?? {});
      return;
    }
    if (obj.id !== undefined && this.pending.has(obj.id as number)) {
      const p = this.pending.get(obj.id as number)!;
      this.pending.delete(obj.id as number);
      if (obj.error) {
        p.reject(new Error(`ACP error: ${JSON.stringify(obj.error)}`));
      } else {
        p.resolve(obj.result);
      }
      return;
    }
  }

  /** Send a JSON-RPC request and wait for the response. */
  private async _request(method: string, params?: Record<string, unknown>): Promise<unknown> {
    if (!this.proc) throw new Error("ACP client not started");
    const id = this.nextId++;
    const payload = JSON.stringify({ jsonrpc: "2.0", method, id, params: params ?? {} });
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc!.stdin!.write(payload + "\n");
    });
  }

  /** Send a JSON-RPC notification (no response expected). */
  private _notify(method: string, params?: Record<string, unknown>): void {
    if (!this.proc) throw new Error("ACP client not started");
    const payload = JSON.stringify({ jsonrpc: "2.0", method, params: params ?? {} });
    this.proc.stdin!.write(payload + "\n");
  }

  // ── Public API ──

  async initialize(): Promise<InitializeResult> {
    return this._request("initialize") as Promise<InitializeResult>;
  }

  async authenticate(): Promise<void> {
    await this._request("authenticate");
  }

  async sessionNew(): Promise<SessionNewResult> {
    return this._request("session/new") as Promise<SessionNewResult>;
  }

  async sessionPrompt(sessionId: string, text: string): Promise<PromptResult> {
    return this._request("session/prompt", { sessionId, text }) as Promise<PromptResult>;
  }

  async sessionSetConfigOption(sessionId: string, key: string, value: string): Promise<unknown> {
    return this._request("session/set_config_option", { sessionId, key, value });
  }

  sessionCancel(sessionId: string): void {
    this._notify("session/cancel", { sessionId });
  }

  /** Subscribe to session/update notifications. */
  onUpdate(handler: (update: SessionUpdate) => void): () => void {
    const listener = (method: string, params: Record<string, unknown>) => {
      if (method === "session/update") {
        handler(params as unknown as SessionUpdate);
      }
    };
    this.on("notification", listener);
    return () => this.off("notification", listener);
  }

  /** Stop the ACP subprocess. */
  async stop(): Promise<void> {
    if (this.proc) {
      this.proc.stdin?.end();
      this.proc.kill();
      this.proc = null;
    }
  }
}