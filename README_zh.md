# mini-dsh

[English](README.md) | 中文

**最小化 DeepSeek Harness（dsh）**：用 Python 从零构建的 dsh 工程骨架。

## 项目描述

mini-dsh 是官方 [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness)（dsh）的 Python 教学复刻。官方 dsh 是一个 TypeScript 编写的通用 AI agent 框架：以 Cordis 插件容器为内核，把 agent 的所有能力——会话、模型调用、工具执行、技能、子代理、上下文压缩、token 计量、审批、Web 检索——都实现为**可插拔的插件**，通过 bundle/profile 声明式装配。

mini-dsh 忠实复刻了这一架构：

- **内核**：自研 `cordis/` 插件容器（Context/Fiber/Service/事件派发/四形态归一），约 400 行同步单线程内核，等价官方 `@deepseek-ai/cordis`
- **能力三角色**：每个能力拆成「定义（纯契约）/ 提供方（构造即注册）/ 消费方（写工具注册表）」三层，seam 可替换
- **会话事件流**：append-only 事件日志（20+ 类型白名单），所有可观测行为都落成事件，TUI/持久化/压缩/token 计量都是只读观察者
- **agent-loop**：react 循环驱动器，流式 LLM → 工具调用 → 结果回填 → 再思考，直到文本收尾
- **LLM 软映射层**：四家模型（DeepSeek/Kimi/Qwen/GPT）的思考强度、温度、推理回传差异收敛在纯函数层
- **三种前端门面**：pi-tui 终端（对齐官方 dsh-tui）、Textual TUI（Python 进程内）、ACP JSON-RPC server（供外部程序），经 `--profile` 一键切换
- **真实 token 计量**：provider 回传的 usage（非估算）经 tokenMeter 锚点流转到前端显示

相比官方（TypeScript + 40+ 包），mini-dsh 做了**最小化裁剪**：单仓库单包、同步内核、教学版事件面，但保留全部核心机制形态。所有偏离处标 `[教学简化]`，所有对齐处标 `↔ 官方源码位置`。

## 存在的意义

1. **配合教学，逐机制对齐**：配套教学仓库 [deepseek-harness-anatomy](https://github.com/ChenYu1991ppak/deepseek-harness-anatomy)，本实现完全根据教学内容从 0 构建，每个能力/机制都能与官方 `packages/*/src` 对上号。
2. **Python 开发者自建 agent harness 的起点**：不同分支对应不同构建阶段，可直接作为模板分叉出你自己的 agent harness。

构建原则见 [docs/PRINCIPLES_zh.md](docs/PRINCIPLES_zh.md)。

## 当前特性

- **内核**：Cordis 插件容器（Context/Fiber/Service/事件/四形态归一）
- **会话面**：append-only 事件日志 + 恢复（resume）+ 投影（projection）+ JSONL/SQLite 持久化
- **agent-loop**：react 循环（流式 LLM → 工具 → 回填 → 收尾）+ turn 边界事件
- **LLM**：OpenAI 兼容流式 + 思考五档 + 软映射层（四家模型收敛）+ 真实 token 用量（provider 回传）
- **工具**：注册表 + 三段守卫管线 + bash/read_file + 审批（ask/never + 应答者）+ 技能加载 + 子代理委派
- **检索**：Web search/fetch（SSRF 防护 + HTML→text）+ LSP 四操作
- **压缩**：上下文压缩（阈值触发，prune/summarize）
- **前端**：pi-tui 终端 + Textual TUI + ACP JSON-RPC server，经 `--profile` 切换
- **装配**：bundle/profile 覆盖链 + `minidsh plugin` 管理

完整列表见 [docs/FEATURE_zh.md](docs/FEATURE_zh.md)。

## 运行

### 安装

```bash
git clone https://github.com/ChenYu1991ppak/Minidsh.git
cd Minidsh
pip install -e . --no-build-isolation

# 配置模型（必须）
mkdir -p ~/.minidsh
# models.json 内嵌 apiKey，见 docs/PRINCIPLES_zh.md §8
```

### 启动 TUI

```bash
minidsh --profile tui [./project]          # pi-tui 前端（需 API key）
```

### 自定义 profile

`--profile <name>` 启动自定义 profile 或内置 bundle。详细编写方法见 [docs/PRINCIPLES_zh.md §7](docs/PRINCIPLES_zh.md#7-bundle--profile-规约)。

```yaml
# ~/.minidsh/profiles/my.yaml
bundles: [tui]          # 在 base 上叠加 tui 前端
plugins:                # 追加/覆盖插件
  - my-extra-plugin
remove: [minidsh.llm-openai]  # 移除插件
```

```bash
minidsh --profile my [./project]
```

## 未来工作（按实现顺序）

1. **session-title** — LLM 自动生成会话标题（当前为确定性 fallback）
2. **fs-search + str-replace-editor** — 文件搜索与编辑工具（grep/glob + 编辑器）
3. **plan + todo** — 任务规划与待办清单面板
4. **commands 完整注册表** — 命令 ScopedLayers（per-agent 隔离）
5. **ask-user** — 用户提问工具
6. **terminal** — PTY 终端工具
7. **workflow + mcp** — 多 agent 编排 + MCP 协议

## License

[MIT](LICENSE)