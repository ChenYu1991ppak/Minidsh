# pi-tui Ecosystem Choice

English | [中文](pi-tui_zh.md)

## Why pi-tui

mini-dsh uses pi-tui as its TUI frontend:

| Frontend | Tech stack | Form | Use case |
|---|---|---|---|
| mini-dsh TUI | TypeScript + `@earendil-works/pi-tui` | Standalone Node.js process, ACP protocol | Aligned with the official dsh-tui ecosystem, software-development terminal |

## Decision Rationale

1. **Official choice**: `@deepseek-ai/dsh-tui` (1993-line index.ts) uses `@earendil-works/pi-tui` as its core rendering library,
   authored by mitsuhiko/badlogic, veterans in the terminal-tooling space (pygments / insta / pixi, etc.). It is the official
   "terminals-as-first-class" implementation path.

2. **Differential rendering**: pi-tui's `TuiMainScreen` updates only the changed lines (differential rendering),
   naturally immune to freezing on 79KB text — complementing Textual's full-text Rich Text layout.

3. **Process isolation**: the pi-tui frontend communicates with the Python backend over the ACP stdio protocol, mutually
   non-blocking. Python runs agent/session/tools; Node only handles terminal rendering + input — clear responsibilities.

4. **Ecosystem alignment**: third-party extensions such as `@narumitw/pi-tui-kit` (declarative UI flows)
   have already formed a pi-tui component ecosystem; existing extensions can be reused rather than writing new components.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Terminal (user)                                     │
├─────────────────────────────────────────────────────┤
│ pi-tui frontend (Node.js)                           │
│  ├─ acp-client.ts  ── spawn pydsh --profile acp   │
│  ├─ session-state.ts ── local session projection    │
│  └─ index.ts         ── pi-tui component tree       │
├─────────────────────────────────────────────────────┤
│ ACP JSON-RPC stdio (ndjson, one JSON object per line)│
├─────────────────────────────────────────────────────┤
│ mini-dsh Python backend                             │
│  ├─ acp-server  ── receives JSON-RPC, drives agent loop │
│  ├─ agent-loop  ── ReactLoopAgent                   │
│  └─ session/llm/tools ── core capabilities          │
└─────────────────────────────────────────────────────┘
```

## Running

```bash
# 1. Install frontend dependencies
cd /path/to/pydsh/infrastructure/tui/pi-tui && npm install && npm run build

# 2. Start (requires the pydsh Python backend installed)
cd /path/to/project && npx tsx /path/to/pydsh/infrastructure/tui/pi-tui/src/index.ts

# 2b. Or via the launcher (forthcoming)
pydsh --profile tui   # auto-spawns the pi-tui frontend
```

## Testing

The pi-tui frontend has no automated tests yet (requires a real TTY environment). The Python-side ACP protocol
is covered by 18 tests (`tests/tools/test_acp.py`).

## References

- [@earendil-works/pi-tui@0.85.0](https://www.npmjs.com/package/@earendil-works/pi-tui) — npm package
- [pi-tui README](https://github.com/earendil-works/pi) — source repository
- [Toad](https://batrachian.ai) — a reasoning-focused AI coding terminal in the pi-tui ecosystem
- Official dsh-tui (removed, commit `10bb9cbf4a`) — 1993-line index.ts, 833-line transcript.ts, 328-line theme.ts

## Rendering Comparison vs. Official dsh-tui

| Dimension | Official dsh-tui (removed) | mini-dsh pi-tui frontend |
|---|---|---|
| Transcript model | Single ordered timeline (append-origin) | ✅ Same single ordered `items`, tool cards render inline between messages |
| Tool card | `ToolCardComponent` three-stage fold (hidden/collapsed/expanded) | ✅ Same three-stage fold (Ctrl+O cycle) |
| Fold preview | `preview(body, maxOutputLines)` first N lines + `… +N lines` hint | ✅ First 6 lines preview + `… +N lines (Ctrl+O to expand)` |
| Card header | `○/● Tool / <name>` ring marker + status color | ✅ `○/● Tool / <name>` + warning/success/error status colors |
| Output cap | `maxToolOutputLines` (configurable) | ✅ `TOOL_PREVIEW_LINES = 6` (compile-time constant) |
| Reasoning render | Optional display + italic dim | ⚠ Folded to 200 chars + dim (no expand/collapse hotkey) |
| Status colors | palette: dim/accent/success/warning/error/code | ⚠ First five + ANSI escapes, no standalone Palette type / 6-color code distinction |
| Token usage | `tokenMeter` live footer bar | ⚠ `usage` field exists, but ACP doesn't map `usage_update`; no live footer refresh |
| Diff card | `renderDiff` add/remove line coloring | ❌ Not implemented (no `diff` tool presentation) |
| Markdown render | `Markdown` component (code highlight/tables/links) | ⚠ Plain-text wrap (no code-block coloring) |

## Known Gaps (by priority)

1. **Token usage doesn't refresh**: the ACP server doesn't map `tokenMeter.measure()` to `usage_update`; the frontend footer `usage` stays empty.
2. **Markdown isn't colored**: assistant replies are plain text; code blocks/tables/links aren't rendered with the `Markdown` component.
3. **Tool-output truncation is hardcoded**: `TOOL_PREVIEW_LINES`/`MAX_TOOL_RESULT_CHARS` should come from config.
4. **Trailing output drag-select**: official body lines have no prefix (drag-select copies only tool text); this version has a 2-space indent.