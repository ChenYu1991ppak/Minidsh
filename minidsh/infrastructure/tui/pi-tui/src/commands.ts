/**
 * Slash command registry for pi-tui frontend.
 *
 * @module minidsh-pi-tui/commands
 */

export interface Command {
  name: string;
  description: string;
  handler: (args: string) => void | Promise<void>;
}

export class CommandRegistry {
  private commands = new Map<string, Command>();

  register(cmd: Command): void {
    this.commands.set(cmd.name, cmd);
  }

  dispatch(line: string): boolean {
    const trimmed = line.trim();
    if (!trimmed.startsWith("/")) return false;
    const spaceIdx = trimmed.indexOf(" ");
    const cmdName = spaceIdx > 0 ? trimmed.slice(1, spaceIdx) : trimmed.slice(1);
    const args = spaceIdx > 0 ? trimmed.slice(spaceIdx + 1).trim() : "";
    const cmd = this.commands.get(cmdName);
    if (!cmd) return false;
    cmd.handler(args);
    return true;
  }

  helpText(): string {
    const lines = ["Available commands:"];
    for (const [name, cmd] of this.commands) {
      lines.push(`  /${name} — ${cmd.description}`);
    }
    return lines.join("\n");
  }
}