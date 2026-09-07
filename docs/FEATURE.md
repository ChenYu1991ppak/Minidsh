# mini-dsh v1 版本特性

> v1 = 在 v0 基础上补齐「会话恢复 + 思考模式 + TUI 交互」。
> 对应分支：`v1`（commit `b6b0b0e`，即 v0 之上的 27 个增量）。

## 会话面「读」半边 + 恢复

- **`scope` 库原语**（`packages/core/scope`）：`createScope` / `ScopedLayers` —— per-agent 隔离根基；`Context.extend` 子容器（读继承、写孤立）。
- **`ctx.agents` 独立注册表** + `AgentFactory`（loop 经 `setFactory` 注册，可替换）。
- **`ctx.subprocess`** 独立 seam（完全显式 spawn + `DSH_*` 环境清除 + 有界 collect/spill）。
- **`ctx.sandbox`** 真 confining（bwrap：`read-only` / `workspace-write`）。
- **`ctx.settings`** 分层设置 seam。
- **`ctx.sessionProjections`** 投影 seam（纯 `apply` fold + snapshot + 变更馈送；落地 `lastMessage` 单元）。
- **会话恢复（resume）**：`SessionStore.resume` + `loop.resume` + `derive_messages`（事件流→wire 消息反投影）；CLI `--session <id>`；**默认接上次会话**（`PersistenceBackend.latest`）。

## LLM 思考模式 / 强度 / 温度

- **`reasoningEffort` 五档**（off / minimal / low / medium / high，默认 medium）+ 解析期校验。
- **`softmap` 软映射层**：按 model id 家族判别，四家差异收敛——
  - `is_reasoning_model` / `requires_reasoning_history` / `reasoning_effort_map` / `thinking_optin` / `strip_tuning`。
  - DeepSeek `thinking.type` + `reasoning_effort`；Kimi K3/K2.6/K2.7 分族；Qwen `enable_thinking`；GPT o-series `reasoning_effort`。
  - 温度剥离（reasoning 模型固定采样）；诚实降级（DS/Kimi 无 medium、K3 无法关、GPT 无逐字思考流）。
- **`reasoning-delta` chunk** + `reasoning-chunk` / `model-change` 会话事件。
- **回传协议**：`reasoning_content` 持久进历史，每次按当前 model 现算 echo/strip（模型切换安全）。
- **`reconfigure(spec)`**：运行时切模型/温度/强度。

## TUI 交互（替换 CLI `run`）

- `minidsh`（无子命令）直接启动 Textual TUI，默认 cwd 为项目根；`replay` / `plugin` 保留为子命令。
- **视图模型解耦**：`transcript.fold`（事件→turn 树，纯函数不碰 Textual）+ Textual App。
- **思考/回复分色流式显示**（rich.Text，思考 dim italic）。
- **斜杠命令**：`/model`、`/thinking`、`/new`（进程内切新会话）、`/exit`。
- **滚动跟随输出** + 垂直滚动条。
- 修复：payload 方括号被当 markup（改 rich.Text）、高频 chunk 逐条刷新压垮循环（合并刷新）、`/new` 撞名 seq 断裂。

## 测试

- 测试套件进版本控制；`python -m pytest` 354 全绿，覆盖 ~93%。
- 会话恢复 / 思考软映射 / TUI Pilot / resume 撞名 等专项回归。