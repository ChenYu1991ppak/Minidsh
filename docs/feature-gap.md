# pydsh Feature Gap Analysis

> 对比基准：官方 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) v0.1.3-alpha.2
> 参考文档：`deepseek-harness-anatomy/` 17 章解剖教程 + `learn-deepseek-harness/` 上游分析报告
> 生成日期：2026-09-08

---

## 总览

pydsh 已实现 deepseek-harness 的核心架构骨架（Cordis 内核、agent-loop、session 持久化、工具执行管线、LLM 适配、compaction、subagent、skill、web/lsp、approval、ACP/TUI 前端），但以下特性尚未实现。按重要性分为 P0（阻断级）、P1（高优先级）、P2（中优先级）、P3（低优先级/实验性）四级。

---

## P0 — 阻断级缺失（影响基本功能完整性）

### 1. 文件写入/编辑工具链（Write / Edit / Glob / Grep）

**现状**：pydsh 只有 `read_file`，没有 `Write`、`Edit`、`Glob`、`Grep`。

**影响**：模型无法写入或修改文件，无法搜索代码库。这是 agent 最基本的能力——没有写入能力，agent 只能读不能说"做"。

**官方对应**：
- `packages/fs/tool-fs` — Read / Write / Edit / ReadImage
- `packages/fs/tool-fs-search` — Glob / Grep
- `packages/fs/tool-str-replace-editor` — 基于字符串替换的编辑器

**教学建议**：至少实现 Write + Grep（Read 已有），Edit 可以用简单的 str-replace 语义。

**对应章节**：anatomy ch04（工具注册执行管线）、ch06（执行世界 ctx.fs）

---

### 2. TodoWrite 工具

**现状**：缺失。

**影响**：模型无法结构化地跟踪任务进度。这是 Claude Code / dsh 中用于让模型自己管理多步骤任务的核心工具。

**官方对应**：`packages/todo/tool-todo`

**教学建议**：实现简单——维护一个 JSON 任务列表，前端渲染为进度条。

---

### 3. AskUserQuestion 工具

**现状**：缺失。

**影响**：模型无法在遇到歧义时向用户提问。当前只能猜测或硬着头皮执行，缺乏"人机交互闭环"。

**官方对应**：`packages/interaction/tool-ask-user`

**教学建议**：实现一个工具，暂停执行，渲染问题给用户，用户选择后继续。

---

## P1 — 高优先级缺失（影响产品体验和完整性）

### 4. Subagent 控制工具（ListAgents / TaskStop）

**现状**：pydsh 有 `task` 工具（spawn/fork），但没有 `ListAgents` 和 `TaskStop`。

**影响**：模型无法查看当前运行的 subagent 列表，也无法取消正在运行的 subagent。

**官方对应**：
- `packages/subagent/tool-subagent-control` — ListAgents / TaskStop

**对应章节**：anatomy ch11（subagent 委托）

---

### 5. Plan 模式（PlanMode）

**现状**：缺失。

**影响**：模型无法进入"先计划、后执行"的模式。Claude Code 中这是核心工作流——先输出方案获取用户批准，再执行。

**官方对应**：`packages/plan/` — Plan mode as logged state

**教学建议**：实现一个状态机——plan 模式下模型只输出方案，用户确认后切换为执行模式。

---

### 6. Goal 服务 + 目标驱动

**现状**：缺失。

**影响**：缺乏结构化的目标/任务跟踪机制。官方 Goal 服务通过 event sourcing 驱动目标生命周期。

**官方对应**：
- `packages/goal/` — Goal service + tool-goal
- anatomy ch14 部分

---

### 7. Permission Presets（权限预设）

**现状**：pydsh 有 approval 服务（ask/never 策略），但没有预设系统。

**影响**：用户无法预先配置"always allow bash"或"always deny web_fetch"等规则，每次都要手动批准。

**官方对应**：`packages/interaction/permission-presets`

**对应章节**：anatomy ch14（交互、审批、权限）

---

### 8. MCP（Model Context Protocol）集成

**现状**：缺失。

**影响**：无法接入外部 MCP server 的工具。MCP 是 AI 工具生态的标准协议。

**官方对应**：`packages/mcp/mcp-client` — connection, tools, transport

**教学建议**：至少实现 MCP client 的 stdio transport + tool 集成。

---

## P2 — 中优先级缺失（完善产品能力）

### 9. Session 格式版本化 + 迁移

**现状**：pydsh 的 session 事件格式没有版本化机制。

**影响**：未来如果事件格式变更，旧 session 无法回放。

**官方对应**：`packages/session/session-format` — v0-to-v1, v1-to-v2 迁移

---

### 10. Session Telemetry（遥测）

**现状**：缺失。

**影响**：无法收集 session 级别的用量统计、延迟指标等。

**官方对应**：`packages/session/session-telemetry` + `session-telemetry-otel`

---

### 11. Preset（agent 预设）系统

**现状**：pydsh 有 bundle/profile 组合，但没有 per-session 的 agent-preset。

**影响**：无法为不同 session 使用不同的 agent 配置（不同工具集、不同模型）。

**官方对应**：`packages/preset/agent-presets`

**对应章节**：anatomy ch15（preset/bundle/profile 组合）

---

### 12. PTC（Program-to-Call）模式

**现状**：缺失。pydsh 只有 native 工具呈现模式。

**影响**：无法支持 SDK 编程模式（模型通过 `run_code` 工具执行 Python/TypeScript 代码来调用工具）。

**官方对应**：
- `packages/core/tools` — ptc.ts, presentAs 模式
- anatomy ch16（typert/api/sdk）+ ch17（workflow/Ralph/Python SDK）

---

### 13. 工具超时 + 并发安全

**现状**：缺失。工具没有超时机制，也没有并发安全标记。

**影响**：长时间运行的工具可能卡住整个 agent loop。

**官方对应**：`packages/guard/timeout-policy`；ToolDefinition 的 `isConcurrencySafe` / `timeoutMs`

---

### 14. Cordis 内省/插件调试工具

**现状**：缺失。

**影响**：无法在运行时查看已加载的插件、Fiber 状态、API 目录。

**官方对应**：`packages/extensions/tool-cordis` — plugin/Fiber introspection, API catalog, inspect

---

### 15. Hooks 系统

**现状**：缺失。

**影响**：无法在 agent 生命周期的关键节点（pre-turn, post-tool 等）注入自定义逻辑。Claude Code 的 hooks 是其可扩展性的核心。

**官方对应**：
- `packages/hooks/hook-protocol` — wire-protocol library
- `packages/hooks/hooks-claude-code` / `hooks-codex`

---

### 16. Session Query 工具

**现状**：缺失。

**影响**：模型无法查询历史 session 数据（如"上次是怎么修复那个 bug 的"）。

**官方对应**：`packages/session-query/tool-session-query`

---

### 17. 多 Subagent Provider（ACP / Claude Code / Codex）

**现状**：pydsh 只有 in-process spawn/fork 两种 provider。

**影响**：无法跨进程/跨机器委派 subagent。

**官方对应**：
- `packages/subagent/subagent-acp`
- `packages/subagent/subagent-claude-code`
- `packages/subagent/subagent-codex`
- `packages/subagent/subagent-dsh-sdk`

---

### 18. 多 Provider LLM 架构

**现状**：pydsh 的 LLM 适配层已预留 seam（`LlmRuntime`），但只有 OpenAI 兼容 provider。

**影响**：无法直接接入 Anthropic、Google 等非 OpenAI 兼容 API。

**官方对应**：`packages/llm/llm-deepseek` — 官方目前也只有 DeepSeek provider，但 seam 设计支持多 provider。

---

## P3 — 低优先级/实验性（可选或教学版不适用）

### 19. Web 前端

**现状**：缺失。

**官方对应**：`apps/web/` + `packages/client/web/` + 大量 `packages/client/ui-*` React 组件

**评估**：UI 工程量巨大，教学版不做。

---

### 20. Desktop 应用（Electron）

**现状**：缺失。

**官方对应**：`apps/desktop/` + `apps/desktop-host/`

**评估**：平台级产品，教学版不做。

---

### 21. Agent Teams（多 agent 协作）

**现状**：缺失。

**官方对应**：`packages/experimental/tool-agent-team`（实验性）

**评估**：上游分析报告将其列为新章节候选，但仍在实验阶段。教学版可暂不做。

---

### 22. Workflow 引擎

**现状**：缺失。

**官方对应**：`packages/workflow/` — workflow capability + worker-thread provider + tool-workflow

**对应章节**：anatomy ch17

**评估**：复杂的多步骤编排，教学版可后续考虑。

---

### 23. Ralph 循环（定时任务）

**现状**：缺失。

**官方对应**：`packages/workflow/tool-ralph` — recurring prompt/command loop

**评估**：与 workflow 紧密相关，教学版可后续考虑。

---

### 24. Webhook 运行时

**现状**：缺失。

**官方对应**：`packages/webhook/`（上游新增）

**评估**：上游分析报告将其列为新章节候选 #1。fire-and-forget HTTP 事件触发 agent。

---

### 25. Terminal 持久会话

**现状**：缺失。bash 工具每次调用都是独立进程。

**官方对应**：`packages/terminal/` + `packages/shell/tool-bash-persistent`

**评估**：高级特性，需要 PTY 管理。

---

### 26. 代码运行时（Python SDK / Code Runtime）

**现状**：缺失。

**官方对应**：`python/sdk/` + `python/sdk-runtime/` + `packages/experimental/code-runtime-python`

**评估**：PTC 模式的基础设施，教学版可后续考虑。

---

### 27. Background Jobs

**现状**：缺失。

**官方对应**：`packages/jobs/tool-jobs`

**评估**：后台任务管理，与 terminal 和 workflow 相关。

---

### 28. Windows 支持（PowerShell / ACL Sandbox）

**现状**：缺失。pydsh 目前仅 Linux/macOS。

**官方对应**：
- `packages/shell/tool-pwsh` / `tool-pwsh-persistent`
- `packages/sandbox/sandbox-windows-acl`

**评估**：平台支持，教学版不做。

---

### 29. TypeScript SDK / JSON-RPC Client

**现状**：缺失。

**官方对应**：`packages/sdk/` — JSON-RPC protocol + TypeScript client/server

**评估**：pydsh 通过 ACP 协议间接支持外部客户端，不需要独立 SDK。

---

### 30. Landlock 沙箱

**现状**：pydsh 用 bwrap 做沙箱。

**官方对应**：`native/landlock-run` — Linux Landlock 原生 addon

**评估**：bwrap 已足够，Landlock 是更细粒度的替代方案。

---

## 与 Anatomy 章节的对应关系

| Anatomy 章节 | pydsh 实现状态 |
|---|---|
| ch01 Cordis 内核 | ✅ 完整（4-state fiber，教学简化） |
| ch02 Agent Loop | ✅ 完整 |
| ch03 Session 持久化 | ✅ 完整（JSONL + SQLite） |
| ch04 工具注册执行 | ✅ 完整（guard/validate/pipeline） |
| ch05 Capability Seam | ✅ 完整（三角色抽象） |
| ch06 执行世界 | ✅ 完整（shell/fs/subprocess/sandbox） |
| ch07 LLM 适配 | ✅ 完整（softmap + reasoning） |
| ch08 System Prompt | ✅ 完整 |
| ch09 Scope 作用域 | ✅ 完整（ScopedLayers） |
| ch10 Compaction | ✅ 完整（basic engine） |
| ch11 Subagent | ⚠️ 部分（in-process 有，无 ACP/codex/claude-code provider，缺 ListAgents/TaskStop） |
| ch12 Skill | ✅ 完整 |
| ch13 Web/LSP | ✅ 完整（LSP 留桩） |
| ch14 交互/审批/权限 | ⚠️ 部分（approval 有，缺 Goal/Plan/AskUser/权限预设） |
| ch15 Preset/Bundle/Profile | ⚠️ 部分（bundle/profile 有，缺 preset） |
| ch16 Typert/API/SDK | ❌ 全部缺失（PTC 模式、typert 类型图、RPC gateway） |
| ch17 Workflow/Ralph/Python | ❌ 全部缺失（workflow、Ralph、Python SDK） |

---

## 上游分析报告中的新候选章节

来自 `learn-deepseek-harness/upstream-analysis/`：

| 候选 | 主题 | pydsh 状态 |
|---|---|---|
| #1 | Webhook runtime | ❌ 缺失 |
| #2 | Agent Teams | ❌ 缺失 |
| #3 | Web Client 架构 | ❌ 缺失 |
| ch07 合并 | DeepSeek API wire 扩展 | N/A（pydsh 用 OpenAI 兼容 API） |

---

## 优先级排序总结

| 优先级 | 数量 | 关键项 |
|---|---|---|
| P0 | 3 | Write/Edit/Glob/Grep 工具链、TodoWrite、AskUserQuestion |
| P1 | 5 | Subagent 控制工具、Plan 模式、Goal 服务、Permission Presets、MCP 集成 |
| P2 | 10 | Session 格式版本化、Telemetry、Preset、PTC 模式、工具超时、Cordis 内省、Hooks、Session Query、多 Subagent Provider、多 LLM Provider |
| P3 | 12 | Web 前端、Desktop、Agent Teams、Workflow、Ralph、Webhook、Terminal、Code Runtime、Background Jobs、Windows 支持、TypeScript SDK、Landlock |

**建议的下一步**：优先实现 P0 的 3 项（Write/Edit/Glob/Grep 工具链 + TodoWrite + AskUserQuestion），然后进入 P1。