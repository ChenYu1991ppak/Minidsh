# pydsh Tool Gap Analysis

> 对比基准：官方 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) v0.1.3-alpha.2
> 生成日期：2026-09-08

---

## 总览

官方 deepseek-harness 共有 **23 个工具包**（含 PTC 内置工具），定义了约 30+ 个模型可调用的工具。pydsh 目前实现了 **7 个工具**（bash、read_file、web_search、web_fetch、lsp、skill-catalog、task），缺失约 23+ 个工具。

---

## pydsh 已实现的工具

| # | 工具名 | 对应官方 | 状态 |
|---|---|---|---|
| 1 | `bash` | `packages/shell/tool-bash` → `Bash` | ✅ 完整 |
| 2 | `read_file` | `packages/fs/tool-fs` → `Read` | ✅ 完整 |
| 3 | `web_search` | `packages/web/tool-web` → `WebSearch` | ✅ 完整 |
| 4 | `web_fetch` | `packages/web/tool-web` → `WebFetch` | ✅ 完整 |
| 5 | `lsp` | `packages/lsp/tool-lsp` | ⚠️ 有（provider 留桩） |
| 6 | `skill-catalog` | `packages/skill/tool-skill` → `Skill` | ✅ 完整 |
| 7 | `task` | `packages/subagent/tool-subagent` → `SendMessage` | ✅ 完整 |

---

## 缺失的工具（按重要性分级）

### P0 — 阻断级（没有这些工具，agent 基本无法工作）

#### 1. Write / Edit — 文件写入和编辑

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/fs/tool-fs` → `Write` / `Edit`；`packages/fs/tool-str-replace-editor` |
| **功能** | 写入新文件、基于字符串替换编辑已有文件 |
| **影响** | 没有写入能力，agent 只能读不能说"做"。这是最核心的缺失。 |
| **Schema** | `Write: { file_path: string, content: string }`；`Edit: { file_path: string, old_string: string, new_string: string, replace_all?: bool }` |
| **依赖** | `ctx.fs`（已有） |
| **实现难度** | 低——Edit 用 str-replace 语义即可，不需要 diff 算法 |

#### 2. Glob — 文件模式匹配

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/fs/tool-fs-search` → `Glob` |
| **功能** | 按 glob 模式查找文件 |
| **影响** | 模型无法按文件名模式搜索文件，只能盲猜路径 |
| **Schema** | `{ pattern: string, path?: string }` |
| **依赖** | `ctx.fs`（已有）或 `glob`/`pathlib` |
| **实现难度** | 极低——Python 的 `pathlib.Path.glob()` 或 `glob` 模块 |

#### 3. Grep — 内容搜索

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/fs/tool-fs-search` → `Grep` |
| **功能** | 在文件中搜索匹配的文本/正则表达式 |
| **影响** | 模型无法搜索代码内容，只能打开文件逐行读。没有 grep 的 agent 在代码库中是盲人。 |
| **Schema** | `{ pattern: string, path?: string, include?: string }` |
| **依赖** | `ctx.shell`（已有）或 Python `re` 模块 |
| **实现难度** | 低——可以用 `grep` 命令或 Python 实现 |

#### 4. TodoWrite — 任务列表

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/todo/tool-todo` → `TodoWrite` |
| **功能** | 创建和更新任务列表 |
| **影响** | 模型无法结构化地跟踪多步骤任务进度 |
| **Schema** | `{ todos: [{ content: string, status: "pending"|"in_progress"|"completed", activeForm: string }] }` |
| **依赖** | 无（纯会话状态） |
| **实现难度** | 极低——维护一个 JSON 列表，前端渲染 |

#### 5. AskUserQuestion — 向用户提问

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/interaction/tool-ask-user` → `AskUserQuestion` |
| **功能** | 当模型遇到歧义时，向用户提问并等待回答 |
| **影响** | 没有这个工具，模型要么猜测（可能出错），要么拒绝执行 |
| **Schema** | `{ questions: [{ question, header, options: [{ label, description }], multiSelect }] }` |
| **依赖** | Approval 服务（已有）+ TUI/ACP 渲染 |
| **实现难度** | 中——需要渲染多选题 UI，等待用户选择后继续 |

---

### P1 — 高优先级（显著影响产品体验）

#### 6. ListAgents — 列出子 agent

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/subagent/tool-subagent-control` → `ListAgents` |
| **功能** | 列出当前运行的 subagent 及其状态 |
| **影响** | 模型无法知道当前有哪些 subagent 在运行 |
| **Schema** | `{}`（无参数，返回 agent 列表） |
| **依赖** | `ctx.agents`（已有 AgentRegistry） |
| **实现难度** | 低 |

#### 7. TaskStop — 取消子 agent

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/subagent/tool-subagent-control` → `TaskStop` |
| **功能** | 取消正在运行的 subagent |
| **影响** | 无法取消失控的 subagent |
| **Schema** | `{ task_id: string }` |
| **依赖** | `ctx.agents` + `ctx.subagents` |
| **实现难度** | 低 |

#### 8. Goal — 目标管理

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/goal/tool-goal` → `Goal` |
| **功能** | 设定和管理会话级别的目标 |
| **影响** | 缺乏结构化的目标跟踪 |
| **Schema** | `{ action: "create"|"update"|"complete"|"fail", goal: { ... } }` |
| **依赖** | Goal 服务（需新建） |
| **实现难度** | 中 |

#### 9. EnterPlanMode / ExitPlanMode — 计划模式

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/plan/` — Plan mode as logged state |
| **功能** | 进入/退出计划模式。计划模式下模型只输出方案，不执行。 |
| **影响** | 无法实现"先计划、后执行"的安全工作流 |
| **Schema** | `EnterPlanMode: {}`；`ExitPlanMode: { plan: string }` |
| **依赖** | Plan 状态机（需新建） |
| **实现难度** | 中 |

---

### P2 — 中优先级（完善能力）

#### 10. Workflow — 工作流编排

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/workflow/tool-workflow` → `Workflow` |
| **功能** | 执行多步骤工作流脚本 |
| **影响** | 无法编排复杂的多 agent 协作流程 |
| **Schema** | `{ script: string, ... }` |
| **依赖** | Workflow 引擎（需新建） |
| **实现难度** | 高 |

#### 11. Cron / Schedule — 定时任务

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/workflow/tool-ralph` → `Ralph` (loop) |
| **功能** | 定时重复执行某个操作 |
| **影响** | 无法实现"每 5 分钟检查一次部署状态"这类场景 |
| **Schema** | `{ cron: string, prompt: string, recurring?: bool }` |
| **依赖** | Workflow 引擎或独立调度器 |
| **实现难度** | 中 |

#### 12. Session Query — 会话查询

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/session-query/tool-session-query` |
| **功能** | 查询历史 session 数据 |
| **影响** | 模型无法跨 session 引用历史上下文 |
| **Schema** | `{ session_id?: string, query: string }` |
| **依赖** | SessionStore（已有） |
| **实现难度** | 低 |

#### 13. Cordis Inspect — 插件内省

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/extensions/tool-cordis` |
| **功能** | 查看已加载的插件、Fiber 状态、API 目录 |
| **影响** | 无法在运行时调试插件系统 |
| **Schema** | `{ action: "list"|"inspect", target?: string }` |
| **依赖** | Cordis Context（已有） |
| **实现难度** | 低 |

---

### P3 — 低优先级/实验性

#### 14. Terminal 持久会话

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/terminal/tool-terminal` + `packages/shell/tool-bash-persistent` |
| **功能** | 持久化的终端会话，状态在多次调用间保持 |
| **影响** | 每次 bash 调用都是独立进程，无法维护 shell 状态 |
| **实现难度** | 高（需要 PTY 管理） |

#### 15. Background Jobs

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/jobs/tool-jobs` |
| **功能** | 后台任务管理 |
| **影响** | 无法启动后台长时间运行的任务 |
| **实现难度** | 中 |

#### 16. Webhook 触发

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/webhook/` |
| **功能** | 通过 HTTP webhook 触发 agent |
| **影响** | 无法实现外部事件驱动的 agent 触发 |
| **实现难度** | 高（需要 HTTP server + 事件路由） |

#### 17. Agent Team 工具

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/experimental/tool-agent-team` |
| **功能** | 多 agent 团队协作 |
| **影响** | 无法实现复杂的多 agent 协作模式 |
| **实现难度** | 高（实验性功能） |

#### 18. ReadImage — 图片读取

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/fs/tool-fs` → `ReadImage` |
| **功能** | 读取图片文件（多模态模型的视觉能力） |
| **影响** | 模型无法处理图片输入 |
| **Schema** | `{ file_path: string }` |
| **实现难度** | 低（但需要多模态模型支持） |

#### 19. PTC `run_code` — 代码执行工具

| 属性 | 说明 |
|---|---|
| **官方对应** | `packages/core/tools` ptc.ts → `run_code` |
| **功能** | PTC 模式下的唯一工具，执行 Python/TypeScript 代码来调用其他工具 |
| **影响** | 无法使用 SDK 编程模式 |
| **实现难度** | 高（需要代码沙箱运行时） |

---

## 工具总数对比

| 类别 | 官方 | pydsh | 缺失 |
|---|---|---|---|
| 文件系统 | Read, Write, Edit, Glob, Grep, ReadImage | read_file | Write, Edit, Glob, Grep, ReadImage |
| Shell | Bash, Bash (persistent), PowerShell | bash | 持久化 bash, PowerShell |
| Web | WebSearch, WebFetch | web_search, web_fetch | — |
| LSP | LSP 四操作 | lsp | — |
| Subagent | SendMessage, ListAgents, TaskStop | task | ListAgents, TaskStop |
| Skill | Skill | skill-catalog | — |
| 交互 | AskUserQuestion | — | AskUserQuestion |
| 任务管理 | TodoWrite, Goal | — | TodoWrite, Goal |
| 计划 | EnterPlanMode, ExitPlanMode | — | EnterPlanMode, ExitPlanMode |
| 工作流 | Workflow, Ralph (loop) | — | Workflow, Ralph |
| 会话 | Session Query | — | Session Query |
| 内省 | Cordis Inspect | — | Cordis Inspect |
| 终端 | Terminal | — | Terminal |
| 后台 | Jobs | — | Jobs |
| Webhook | (webhook trigger) | — | Webhook |
| Agent Team | (agent team tools) | — | Agent Team |
| PTC | run_code | — | run_code |
| **总计** | **~30** | **7** | **~23** |

---

## 建议实现顺序

1. **第一批（P0，预计 2-3 天）**：Write + Edit + Glob + Grep + TodoWrite + AskUserQuestion
2. **第二批（P1，预计 2-3 天）**：ListAgents + TaskStop + Goal + EnterPlanMode/ExitPlanMode
3. **第三批（P2，预计 3-5 天）**：Workflow + Session Query + Cordis Inspect + Cron
4. **第四批（P3，按需）**：Terminal + Jobs + ReadImage + Webhook + Agent Team + PTC