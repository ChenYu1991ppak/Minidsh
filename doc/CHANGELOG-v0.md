# mini-dsh v0 版本特性

> v0 = 从零搭起「最小化 DeepSeek Harness」的**基础骨架**。
> 对应分支：`v0`（= `origin/v0`，commit `7420a1f`）。

## 核心：Cordis「一切皆插件」内核

- `Context` 四合一：服务解析（`provide/probe/service/has/inject`）、事件派发（`emit/on/serial/waterfall`）、生命周期注册（`effect`）、容器销毁（`dispose`）。
- `Service` 构造即注册；`Fiber` 四态生命周期 + 「变化即重载」（依赖服务变更自动重载）。
- 插件四形态归一（module / class / 带 apply 对象 / 函数）→ 统一 `Plugin(name, inject, factory)`。

## 能力三角色抽象

- `CapabilityDefinition`（纯接口）/ `CapabilityProvider`（构造即注册）/ `CapabilityConsumer`（写 tools 注册表）。
- 全部能力按三角色拆分：`shell` / `fs` / `llm` / `prompt` / `compaction` / `skills` / `subagent` / `lsp` / `web` / `permission` / `rpc` + `session` / `tools` / `loop`。

## 核心闭环

- **agent-loop**：`Inbox` + `ReactLoopAgent`（react 决策，一轮内多步工具调用往返）+ `AgentLoop`。
- **session**：append-only 事件流（`SessionEvent` 白名单）+ 持久化（jsonl / sqlite 双后端）。
- **tools**：`ToolDefinition` / `ToolRuntime`，三段守卫管线（pre-execute / execute / post-execute）。
- **llm**：OpenAI 兼容流式 provider（接口屏蔽 SDK 类型）。
- **prompt**：分节注册/组装（system-prompt section）+ AGENTS.md 注入。
- **skills / subagent / compaction**：技能目录、in-process 子 agent 委派、token 压力压缩。

## 装配与打包

- **bundle + profile**（无 manifest 一词）：`Bundle(name, plugins, remove)` + profile 覆盖链（默认 base < 命名 < 项目 < 用户 < argv）。
- **entry-point 发现**：插件组 `minidsh.plugins`，内置与第三方同机制。
- **目录结构**：`cordis/`（内核）+ `packages/{services,tools}/`（能力/工具）+ `infrastructure/`（装配/配置/打包）+ `bundles/`（清单）。

## CLI 与观测

- `minidsh run` / `minidsh replay` / `minidsh plugin`。
- `trace-render`（ConsoleRenderer）实时透出事件流 + `replay` 回放落盘会话。

## 文档

- `doc/PRINCIPLES.md` 构建原则手册（世界观 / 三角色规约 / 命名 / 测试 / 迭代检查清单）。
