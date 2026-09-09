# pydsh

English | [中文](README_zh.md)

**A minimal DeepSeek Harness in Python.** Plugin loop, hooks, permissions, goals/plans — one command, zero config. A faithful educational reproduction of the dsh engineering skeleton, built from scratch.

> DeepSeek Harness (dsh) is an AI agent framework. This is its Python twin — same architecture, minimal cut, ready to run. [deepseek-harness-anatomy](https://github.com/ChenYu1991ppak/deepseek-harness-anatomy) is the companion tutorial that explains every mechanism.

![Pydsh Architecture](assets/pydsh-architecture.html)

## Who Should Use This

- **You want a Python agent harness that works today** — clone, configure an API key, run `make tui`, and you have a daily coding agent with tools, skills, subagents, and compaction
- **You're studying agent architecture** — every mechanism is aligned to the official dsh source (`↔ packages/*/src`), with teaching simplifications explicitly marked
- **You're building your own agent framework** — fork it as a template; the Cordis plugin container, seam triple-role pattern, and event-stream persistence are all reusable
- **You read the companion tutorial** [deepseek-harness-anatomy](https://github.com/ChenYu1991ppak/deepseek-harness-anatomy) and want to see the real thing in Python

## Project Description

pydsh is a Python educational reproduction of the official [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness) (dsh). The official dsh is a TypeScript general-purpose AI agent framework: powered by the Cordis plugin container, it implements every agent capability — sessions, model calls, tool execution, skills, subagents, context compaction, token metering, approval, web retrieval — as **pluggable plugins**, assembled declaratively through bundles and profiles.

pydsh faithfully reproduces this architecture:

- **Kernel**: a custom `cordis/` plugin container (Context / Fiber / Service / event dispatch / four-form normalization), ~400 lines of synchronous single-threaded kernel, equivalent to the official `@deepseek-ai/cordis`
- **Capability tri-role**: every capability is split into three layers — definition (pure contract) / provider (self-registering on construction) / consumer (writes to the tool registry) — making seams replaceable
- **Session event stream**: an append-only event log (20+ type whitelist); every observable behavior is recorded as an event, with TUI, persistence, compaction, and token metering as read-only observers
- **Agent loop**: a react-style loop driver — streaming LLM → tool calls → result backfill → re-think → until text settlement
- **LLM soft-mapping layer**: reasoning effort, temperature, and reasoning history for four model families (DeepSeek / Kimi / Qwen / GPT) are converged in pure functions
- **pi-tui terminal frontend**: TypeScript + `@earendil-works/pi-tui`, standalone Node.js process communicating via ACP JSON-RPC stdio protocol, aligned with the official dsh-tui
- **Real token usage**: provider-returned usage (not estimates) flows through the `tokenMeter` anchor to the frontend display

Compared to the official version (TypeScript + 40+ packages), pydsh is **minimally cut**: a single-repo single-package layout, synchronous kernel, and an educational event surface, while preserving all core mechanism shapes. Every deviation is marked `[教学简化]` (teaching simplification), and every alignment is marked `↔ official source location`.

## Current Features

- **Kernel**: Cordis plugin container (Context / Fiber / Service / events / four-form normalization)
- **Session**: append-only event log + resume + projections + JSONL / SQLite persistence
- **Agent loop**: react loop (streaming LLM → tools → backfill → settlement) + turn boundary events
- **LLM**: OpenAI-compatible streaming + five reasoning effort levels + soft-mapping layer (four model families converged) + real token usage (provider-returned)
- **Tools**: registry + three-stage guard pipeline + bash / read_file + approval (ask / never + answerer) + skill loading + subagent delegation
- **Retrieval**: web search / fetch (SSRF protection + HTML→text) + LSP four operations
- **Compaction**: context compaction (threshold-triggered, prune / summarize)
- **Frontend**: pi-tui terminal + ACP JSON-RPC server, switchable via `--profile`
- **Assembly**: bundle / profile overlay chain + `pydsh plugin` management

Full list: [docs/FEATURE.md](docs/FEATURE.md).

## Project Structure

```
pydsh/
├── Makefile                          # Task automation
├── scripts/
│   └── setup.sh                      # One-click install script
├── pydsh/                          # Python package
│   ├── __init__.py
│   ├── cordis/                       # Plugin container kernel
│   ├── infrastructure/               # Boot, config, bundle, profile, packaging, tui
│   │   ├── boot/                     # CLI entry + project loader
│   │   ├── bundle/                   # Bundle manifest loading
│   │   ├── config/                   # Config / models.json / settings.json
│   │   ├── packaging/                # Plugin discovery (entry-points)
│   │   ├── profile/                  # Profile overlay chain
│   │   └── tui/                      # pi-tui launcher + Node.js frontend
│   │       ├── app_pi_tui.py         # App plugin: spawns pi-tui subprocess
│   │       └── pi-tui/               # Node.js frontend (ACP client)
│   ├── packages/
│   │   ├── core/                     # Shared library primitives
│   │   ├── services/                 # Capability services (20+ capabilities)
│   │   └── tools/                    # Consumer tools (bash, read_file, web, lsp)
│   └── bundles/                      # Built-in activation manifests
├── tests/                            # Test suite (pytest)
├── docs/                             # Design docs & principles
└── pyproject.toml                    # Package metadata & entry-points
```

## Quick Start

### Prerequisites

- Python >= 3.11
- Node.js >= 18 (auto-installed by setup script on Linux/macOS)

### 1. Install

```bash
git clone https://github.com/ChenYu1991ppak/Pydsh.git
cd Pydsh
make install
```

This installs Python dependencies (`pip install -e .`), Node.js dependencies, and compiles the pi-tui frontend.

### 2. Configure Your Model

Create `~/.pydsh/models.json` with your API key:

```bash
mkdir -p ~/.pydsh
```

Example `models.json`:

```json
{
  "currentModel": "deepseek",
  "availableModels": [
    {
      "id": "deepseek",
      "baseUrl": "https://api.deepseek.com",
      "apiKey": "sk-your-api-key-here",
      "model": "deepseek-chat"
    }
  ]
}
```

> Format reference: [docs/PRINCIPLES.md §8](docs/PRINCIPLES.md#8-configuration-specification).

### 3. Launch the TUI

```bash
make tui                          # Start pi-tui TUI
```

Or run directly:

```bash
pydsh --profile tui [./project] # pi-tui frontend
```

## Development

```bash
make test       # Run all tests (python -m pytest)
make clean      # Clean build artifacts and caches
```

### Running Without Node.js

If you don't need the TUI frontend, you can use the ACP server directly:

```bash
pydsh --profile acp              # ACP JSON-RPC server (requires API key)
```

## Custom Profiles

`--profile <name>` launches a custom profile or built-in bundle. See [docs/PRINCIPLES.md §7](docs/PRINCIPLES.md#7-bundle--profile-specification) for details.

```yaml
# ~/.pydsh/profiles/my.yaml
bundles: [tui]          # stack the tui frontend on top of base
plugins:                # append / override plugins
  - my-extra-plugin
remove: [pydsh.llm-openai]  # remove plugins
```

```bash
pydsh --profile my [./project]
```

## Future Work (in implementation order)

1. **session-title** — LLM auto-generated session title (currently a deterministic fallback)
2. **fs-search + str-replace-editor** — file search and editing tools (grep / glob + editor)
3. **plan + todo** — task planning and to-do panel
4. **full commands registry** — command ScopedLayers (per-agent isolation)
5. **ask-user** — user-question tool
6. **terminal** — PTY terminal tool
7. **workflow + mcp** — multi-agent orchestration + MCP protocol

## License

[MIT](LICENSE)