# mini-dsh Construction Principles & Conventions

English | [中文](PRINCIPLES_zh.md)

> This is the **rulebook** for mini-dsh: check here first, then modify the code.
> Every principle originates from a landed implementation, not an unrealized ideal.
> Deviations from the official version are marked `[教学简化]` (teaching simplification) or `[偏离]` (deviation) in both code comments and this document.

---

## 1. One-line Positioning

**mini-dsh is an engineering skeleton that faithfully reproduces DeepSeek Harness (dsh) in Python**:
powered by the Cordis "everything is a plugin" container, it strings together agent-loop / tools / skills / subagent /
session event stream / LLM adaptation / compaction, achieving runnable, observable, and traceable.

- The alignment target is the official `packages/*/src` + `docs/subsystems/*`; mechanism names and chapter-by-chapter annotations align with the teaching repository `deepseek-harness-anatomy/` (read-only).
- **Fidelity > simplification**: ensure the mechanism shape is correct first (seam tri-role, event stream, replaceable providers), then worry about implementation difficulty.
- The reference repository `deepseek-harness-anatomy/` is a **read-only** standalone git repo; changes happen only in `pydsh/` and `tests/`.

## 2. Worldview (Three Iron Laws)

1. **Everything is a plugin**: capabilities, tools, observability, assembly — all are plugins, loaded through the unified `ctx.plugin`.
2. **Registration is an effect**: `provide` / `register` / `ctx.effect` are all reversible — teardown removes them, and fiber teardown cleans up disposers in reverse order.
3. **Capability tri-role**: a capability is split into three layers — "definition / provider / consumer" (see §5); this is the foundation of replaceable seams.

**agent = model + harness**: the loop is responsible for "how to run", the LLM for "what to say", and tools + prompt sections for "what can be done".

## 3. Kernel Constraints (cordis/)

The kernel is **synchronous and single-threaded** (spec §11-5). LLM streaming is the only async surface, adapted by the loop layer using asyncio; the kernel never touches asyncio.

| Entity | Convention | Notes |
|---|---|---|
| `Context` | `provide/probe/service/has/inject/plugin/effect/emit/on/serial/waterfall/dispose` | `__getattr__` only intercepts missing attributes → service table; service registration always uses explicit `provide()` (decision G6) |
| `Service` | Self-registering on construction | Automatically removed on teardown (fiber reverse-executes disposers registered via `ctx.effect`) |
| `Fiber` | Four states: PENDING/ACTIVE/UNLOADING/DISPOSED | "Change is reload" when a dependency service is re-`provide`d or `dispose`d |
| `normalize_plugin` | Four forms normalized → `Plugin(name, inject, factory, explicit_name)` | module / class / object with apply / function |
| Name collision | Explicit `name` duplicates **throw ValueError**; derived-name duplicates only warn | Enforced at `ctx.plugin` registration time |

**Change is reload**: fibers subscribe to `service/provide` / `service/dispose` **not through `ctx.effect`** (otherwise teardown would treat the subscription as a disposer and prevent re-loading), but by writing directly to the listener table; removed only on final `dispose()`.

## 4. Directory Responsibilities (do not mix)

```
pydsh/
├── cordis/                # Kernel, independent (equivalent to official @deepseek-ai/cordis)
│   └── capability.py      #   Tri-role abstract base classes
├── infrastructure/        # Support: not capabilities, but assembly/config/packaging/frontends
│   ├── boot/              #   cli (pydsh TUI entry / replay / plugin) + load_project
│   ├── bundle/            #   Bundle / PluginRef / merge / build_context
│   ├── config/            #   Config/ModelSpec + resolve + files + providers
│   ├── packaging/         #   entry-point discovery + plugin commands
│   ├── profile/           #   resolve_profile overlay chain
│   └── tui/               #   Interactive frontends (pi-tui spawner)
├── packages/
│   ├── core/              # Shared "library primitives" (non-ctx services, official core/scope equivalent)
│   │   └── scope/         #   ScopeKey / Scope / ScopedLayers / createScope
│   ├── services/          # Capabilities that provide ctx services (definition + providers/ + helpers)
│   └── tools/             # Consumer tools (bash.py / read_file.py)
└── bundles/               # Activation manifests (pydsh.base.yaml, etc.)
```

**Four partition roles (do not mix)**:

| Directory | Role | Official equivalent |
|---|---|---|
| `cordis/` | Kernel | `@cordisjs/core` |
| `packages/core/` | **Shared library primitives (non-services)** | `packages/core/scope` |
| `packages/services/` | Provide ctx services | `packages/core/{session,tools,agent,agent-loop}` + various `packages/*` |
| `packages/tools/` | Consumer tools | `packages/*/tool-*` |

## 5. Capability Tri-role Specification (process for building a new capability)

Definitions in [cordis/capability.py](../pydsh/cordis/capability.py):

- `CapabilityDefinition`: **pure contract** — only declares class attribute `service_name` + interface methods, never self-registers. Place in `services/<x>/definition.py`.
- `CapabilityProvider`: `Definition + Service`, **self-registering on construction** to `service_name`, override `_init(ctx, *args, **kw)` for initialization (don't manually write `super().__init__(ctx, "x")`). Place in `services/<x>/providers/<name>.py`.
- `CapabilityConsumer`: **not a base class**, stays in module form; only provides `assert_valid(inject, service_name)` validation (`inject` must contain `tools` and the consumed `service_name`). Consumers (in the manifest) go in `packages/tools/*.py`.

**Three-layer iron laws (Never)**:

| Forbidden | Reason |
|---|---|
| Definition registers a service | Registration is the Provider's responsibility |
| Consumer imports a provider class | Consumers only depend on definition + `ctx.<service_name>`; providers are replaceable |
| Provider directly registers a tool | Tools are written by Consumers through `ctx.tools.register` |
| Building a tool for a capability without a model-facing surface | Capabilities without a model-consumption surface (session/compaction/…) don't need the tri-role treatment |

## 6. Plugin Specification

**Four forms** (normalized by [normalize_plugin](../pydsh/cordis/plugin.py)):

```python
# 1) module (the mainstream form for consumer tools / service providers in this project)
name = "pydsh.tool-bash"
inject = ["tools", "shell", "config"]
def apply(ctx): ...

# 2) class (CapabilityProvider subclass, self-registering on construction)
# 3) object with an apply method
# 4) function
```

**Discovery**: entry-point group `pydsh.plugins` (`pyproject.toml`), with entry `name = plugin name`, `value = importable module`.
Built-in and third-party plugins **use the same entry-point discovery** (`entry_point_resolver`, no registry shortcut).
Adding a new built-in plugin = ① write the module ② add an entry-point in pyproject ③ (if default-activated) add to `bundles/pydsh.base.yaml`.

## 7. Bundle / Profile Specification

- **No "manifest" term** (eliminated) — only bundles (declarative activation manifests) and profiles (overlay chains).
- `Bundle(name, plugins, remove)`; bundle file = top-level `plugins:` list (optionally with `remove:`).
- `profile` file = three keys: `bundles:` / `plugins:` / `remove:`.
- **Overlay chain** (later overrides earlier):
  `default [pydsh.base] < named profile < project <project>/.pydsh/profile.yaml < user ~/.pydsh/profile.yaml < argv (when --profile points to a file)`
- `--profile` dual-purpose: file exists → argv overlay path; otherwise → named profile name.
- Provider selection goes through the manifest: CLI `--storage jsonl|sqlite` is translated into "remove the unselected providers, append the selected" — **never enters a provider-internal if branch**.

## 8. Configuration Specification

Two files (aligned with CodeBuddy):
- `models.json` — model configuration, each model embeds `apiKey` (**sensitive**, written with `chmod 600`, never committed to git).
- `settings.json` — harness settings (storage / compaction / tool whitelist), non-secret.

Paths: user-level `~/.pydsh/` (or `$PYDSH_HOME`), project-level `<project>/.pydsh/`.
Priority: project-level overrides user-level; model lists are **concatenated** (same-name id wins at project level), settings keys are **item-overridden**.
Current model: `currentModel` > first entry in `availableModels`.

**Iron law**: no provider abstractions, **no environment variables**, no key leakage — apiKey is only read from `models.json`.

## 9. Tool Specification

- `ToolDefinition(name, description, parameters[OpenAI JSON Schema], execute[async], output[ToolOutput(schema, render)])`
- `ToolOutput.schema` declares the **canonical value** type, `render(args, value)->str` turns it into model-facing content.
- Execution pipeline ([runtime.py](../pydsh/packages/services/tool_runtime/runtime.py)):
  `pre-execute waterfall → monotonic guard → execute → post-execute waterfall`, produces `ToolResult` and broadcasts `tools/result`.
- Arguments take **canonical values** (`execute` receives a dict), JSON deserialization is done by the loop (`_parse_arguments`).
- Tool names follow the official ones (`bash`/`read_file`/`skill-catalog`/`task`).
- Tool whitelist: consumer reads `allowed_tools` via `inject=["config"]`; `None` = all enabled, list excludes skip registration.

## 9-b. LLM Adaptation & Reasoning Mode (Soft-Mapping Layer)

**Seam**: `llm/definition.py` defines `LlmRuntime.stream` + `Chunk` (kernel/loop never imports openai types);
`llm/providers/openai.py` is the only place that imports openai. Adding anthropic later = adding a new provider.

**Five reasoning levels & soft-mapping** ([softmap.py](../pydsh/packages/services/llm/softmap.py)):
- Unified enum `reasoningEffort`: `off / minimal / low / medium / high` (default `medium`),
  stored in `ModelSpec.reasoning_effort`, invalid levels throw `ValueError` at parse time (fail fast).
- **The soft-mapping layer is a pure function, discriminating only by model id family (prefix)**, ignoring the vendor field (aligned with claw-code).
  Four vendors' differences converged in four functions:

  | Function | Purpose |
  |---|---|
  | `is_reasoning_model(id)` | Reasoning/chain-of-thought models → strip temperature/top_p/penalties from requests (fixed sampling; passing them would be rejected with 400) |
  | `requires_reasoning_history(id)` | Families that must echo the previous turn's `reasoning_content` back in multi-turn / tool-call loops (deepseek-v4 / kimi-k3 / kimi-k2.7) |
  | `reasoning_effort_map(id, effort)` | Five levels → each vendor's actual value (nearest-neighbor merging: DS medium→high, K3 high→max, etc.) |
  | `thinking_optin(id, effort)` | Families that need `thinking` / `enable_thinking` switches (DeepSeek / Kimi K2.6 / Qwen) |

- **Temperature semantics**: non-reasoning models pass through; reasoning models strip it (official "reasoning mode doesn't support temperature").
- **Honest reasoning-effort degradation**: DeepSeek/Kimi have no `medium`, K3 cannot be turned off, GPT o-series doesn't return verbatim reasoning streams —
  softmap faithfully merges/ignores, never fakes.

**Streaming reasoning field**: unified `delta.reasoning_content` → `Chunk(kind="reasoning-delta")` → session event
`reasoning-chunk` (whitelisted + persisted). GPT o-series doesn't return reasoning streams, so no reasoning is displayed (API limitation, not a missing implementation).

**Echo protocol (model-switch safe)**: reasoning is **persistent historical data**, stored in `self.messages` as the assistant
message's `reasoning_content` side-channel field; wire serialization decides echo/strip on each request based on the **current model**. So
`/model` switching back and forth within the same session keeps reasoning correctly echoable per the current model's requirements. Pure-text non-tool turns may omit the echo.

## 10. Session Event Contract

- `SessionEventType` whitelist ([event.py](../pydsh/packages/services/session/event.py)):
  `user-message / assistant-chunk / assistant-message / reasoning-chunk / tool-call /
  tool-result / model-change / skill-loaded / subagent-spawn / subagent-result /
  compaction / turn/start / turn/end / session/title / approval/asked / approval/decided / error`.
- **Adding a new event type = adding a member to the whitelist enum** (non-breaking); unknown types are rejected at construction (no dirty data).
- `SessionEvent` frozen (aligned with the official deepFreeze immutability semantics); payload contract: "don't mutate after append".
- **Flush boundary = `assistant-message`** (v1 "one reply" boundary); additionally, `session/flush` event serves as an explicit barrier.

## 10-b. TUI Frontend (pi-tui, ACP protocol)

- **Positioning**: `infrastructure/tui/` hosts the pi-tui launcher, not a `packages/services/` capability.
- **pi-tui frontend**: TypeScript + `@earendil-works/pi-tui`, standalone Node.js process communicating via ACP JSON-RPC stdio protocol.
  Source in `infrastructure/tui/pi-tui/`; launcher plugin in `app_pi_tui.py` spawns the Node.js child process.
- **Process isolation**: Python runs agent/session/tools; Node handles terminal rendering + input only — clear responsibilities, mutually non-blocking.
- **Launch**: `pydsh --profile tui` spawns the pi-tui frontend subprocess and waits for it to exit.
- No `run` subcommand: `pydsh [dir]` (dir defaults to cwd) launches the TUI directly.

## 11. Naming Conventions (summary table)

| Item | Convention | Example |
|---|---|---|
| Plugin name (entry-point key + module `name`) | `pydsh.<lowercase-hyphen>` | `pydsh.tool-bash` / `pydsh.persistence-sqlite` |
| Service name (`service_name`) | camelCase, aligned with official `ctx.<name>` | `systemPrompt` / `agent_loop` / `sessionPersistence` |
| Event name | `domain/action` or kebab-case | `tools/change` / `assistant-message` |
| Directory/module | lowercase_underscore | `tool_runtime` / `read_file.py` |

## 12. Alignment Discipline

- **Annotate source correspondence mechanism by mechanism**: module docstrings and key lines write `↔ index.ts:296`, `corresponds to ch02`, `corresponds to packages/core/agent-loop`.
- **Mark deviations with `[教学简化]`**: where the real version does something the teaching version can't or deliberately cuts (deepFreeze, six-state fiber, zstd compression, timed flush, per-agent scope, etc.), must be declared in comments.
- **Contract object names aligned with official**: `ToolDefinition/ToolExecution/ToolResult/Chunk/SubagentError/…` are isomorphic with the official ones.

## 13. Testing Specification

- Stack: pytest + pytest-asyncio (`asyncio_mode=auto`) + pytest-cov. `pythonpath=["src"]`.
- **Baseline: all green + high coverage** (currently 584 tests / 93%). Changing external behavior must stay green.
- **No StubLlm**: LLM tests use `tests/helpers/`'s `make_fake_llm` (scripted replay) + `openai_fake` (fake client). Kernel/loop never imports openai types.
  - Scripted client supports `{"reasoning": "...", "text": "..."}` turns → produces `reasoning-delta` + `text-delta`.
- **Execution world assembly**: shell-local depends on subprocess; tests use `tests/helpers/world.py`'s `plug_execution_world(ctx)` to plug subprocess→shell→fs in one go, then plugin the tools.
- **bwrap test skip gate**: sandbox uses `pytest.mark.skipif(shutil.which("bwrap") is None)`, skip without bwrap (don't fake full).
- **TUI tests**: pi-tui frontend has no automated tests (requires a real TTY environment).
- **Isolate `PYDSH_HOME`**: `tests/conftest.py` autouse fixture points user config directory to tmp (prevents reading real apiKey).
- Note: **must run with `python -m pytest`** (bare `pytest` lacks the `tests` package path, collect will fail with `No module named 'tests.helpers'`). After changing pyproject's entry-points, re-run `pip install -e . --no-build-isolation` to refresh the discovery cache.

## 14. Version / Release / Sensitive Information

- Version number **single source of truth**: `pydsh/__init__.py`'s `__version__` (pyproject reads it via `attr`).
- Packaging: setuptools, **only publishes the `pydsh/` library** (`packages.find where=["pydsh"]`); tests/examples/doc are not distributed with the library, but doc/ should be in git.
- **Sensitive information**: `apiKey` in plaintext only in `models.json` (`chmod 600` + gitignore); `.env`/`*.key` never committed.

---

## Appendix: Iteration Checklist (review before changing code)

- [ ] Is the new capability split into definition / provider / consumer three layers? Does the consumer register via `ctx.tools.register` rather than providing a new service?
- [ ] Does the new plugin go through entry-point + bundle activation, rather than a hardcoded registry?
- [ ] Have you introduced any "manifest" wording / environment variables / provider abstractions? (all violate iron laws)
- [ ] Are the two "tools" in their correct places (`packages/tools/` vs `tool_runtime/` vs service-root helpers)?
- [ ] Is the event type in the `SessionEventType` whitelist?
- [ ] Does the new model's reasoning effort go through the `softmap` soft-mapping layer (rather than scattered if's in the provider)? Is temperature stripping correct for reasoning models?
- [ ] Does reasoning echo follow "persistent history + decide echo/strip on each request based on the current model", rather than fixed at load time?
- [ ] Do TUI changes only read session/event and never touch core mechanisms?
- [ ] Are deviations from the official version marked `[教学简化]`? Are key source correspondences annotated `↔`?
- [ ] Run with `python -m pytest`, all green + coverage not degraded?