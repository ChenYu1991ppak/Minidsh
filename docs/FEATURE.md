# pydsh v1 Features

English | [中文](FEATURE_zh.md)

> v1 = on top of v0, adds "session resume + reasoning modes + TUI interaction".
> Corresponding branch: `v1` (commit `b6b0b0e`, i.e. 27 increments over v0).

## Session "read" side + resume

- **`scope` library primitives** (`packages/core/scope`): `createScope` / `ScopedLayers` — the foundation for per-agent isolation; `Context.extend` child containers (read-inherit, write-isolate).
- **`ctx.agents` standalone registry** + `AgentFactory` (loop registers via `setFactory`, replaceable).
- **`ctx.subprocess`** standalone seam (fully explicit spawn + `DSH_*` env clearing + bounded collect/spill).
- **`ctx.sandbox`** real confining (bwrap: `read-only` / `workspace-write`).
- **`ctx.settings`** layered settings seam.
- **`ctx.sessionProjections`** projection seam (pure `apply` fold + snapshot + change feed; implements the `lastMessage` unit).
- **Session resume**: `SessionStore.resume` + `loop.resume` + `derive_messages` (event stream → wire-message back-projection); CLI `--session <id>`; **defaults to the last session** (`PersistenceBackend.latest`).

## LLM reasoning modes / effort / temperature

- **`reasoningEffort` five levels** (off / minimal / low / medium / high, default medium) + parse-time validation.
- **`softmap` soft-mapping layer**: discriminates by model id family, converging four vendors' differences —
  - `is_reasoning_model` / `requires_reasoning_history` / `reasoning_effort_map` / `thinking_optin` / `strip_tuning`.
  - DeepSeek `thinking.type` + `reasoning_effort`; Kimi K3/K2.6/K2.7 sub-families; Qwen `enable_thinking`; GPT o-series `reasoning_effort`.
  - Temperature stripping (reasoning models use fixed sampling); honest degradation (DS/Kimi have no `medium`, K3 cannot be turned off, GPT has no verbatim reasoning stream).
- **`reasoning-delta` chunk** + `reasoning-chunk` / `model-change` session events.
- **Echo protocol**: `reasoning_content` persists into history, echoed/stripped on each request based on the current model (model-switch safe).
- **`reconfigure(spec)`**: switch model / temperature / effort at runtime.

## TUI interaction (replaces CLI `run`)

- `pydsh` (no subcommand) launches the Textual TUI directly, default cwd = project root; `replay` / `plugin` remain subcommands.
- **View-model decoupling**: `transcript.fold` (events → turn tree, a pure function that doesn't touch Textual) + Textual App.
- **Reasoning/reply color-coded streaming display** (rich.Text, reasoning dim italic).
- **Slash commands**: `/model`, `/thinking`, `/new` (switch to a new session in-process), `/exit`.
- **Scroll-follow output** + vertical scrollbar.
- Fixes: payload square brackets parsed as markup (switched to rich.Text), high-frequency chunk per-event refresh crushing the loop (merged refresh), `/new` name collision seq break.