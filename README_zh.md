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
- **pi-tui 终端前端**：TypeScript + `@earendil-works/pi-tui`，独立 Node.js 进程经 ACP JSON-RPC stdio 协议通信，对齐官方 dsh-tui
- **真实 token 计量**：provider 回传的 usage（非估算）经 tokenMeter 锚点流转到前端显示

相比官方（TypeScript + 40+ 包），mini-dsh 做了**最小化裁剪**：单仓库单包、同步内核、教学版事件面，但保留全部核心机制形态。所有偏离处标 `[教学简化]`，所有对齐处标 `↔ 官方源码位置`。

## 存在的意义

1. **Minidsh 本身就是一个独立的 agent harness**：以 Cordis 插件容器为内核，会话、循环、LLM、工具、技能、子代理、压缩、token 计量、审批、Web 检索等全部能力都是可插拔的插件。你可以当日常编码 agent 用，也可以组合进你自己的 Python 项目。
2. **配合教学，逐机制对齐**：配套教学仓库 [deepseek-harness-anatomy](https://github.com/ChenYu1991ppak/deepseek-harness-anatomy)，本实现完全根据教学内容从 0 构建，每个能力/机制都能与官方 `packages/*/src` 对上号。
3. **Python 开发者自建 agent harness 的起点**：不同分支对应不同构建阶段，可直接作为模板分叉出你自己的 agent harness。

构建原则见 [docs/PRINCIPLES_zh.md](docs/PRINCIPLES_zh.md)。

## 当前特性

- **内核**：Cordis 插件容器（Context/Fiber/Service/事件/四形态归一）
- **会话面**：append-only 事件日志 + 恢复（resume）+ 投影（projection）+ JSONL/SQLite 持久化
- **agent-loop**：react 循环（流式 LLM → 工具 → 回填 → 收尾）+ turn 边界事件
- **LLM**：OpenAI 兼容流式 + 思考五档 + 软映射层（四家模型收敛）+ 真实 token 用量（provider 回传）
- **工具**：注册表 + 三段守卫管线 + bash/read_file + 审批（ask/never + 应答者）+ 技能加载 + 子代理委派
- **检索**：Web search/fetch（SSRF 防护 + HTML→text）+ LSP 四操作
- **压缩**：上下文压缩（阈值触发，prune/summarize）
- **前端**：pi-tui 终端 + ACP JSON-RPC server，经 `--profile` 切换
- **装配**：bundle/profile 覆盖链 + `minidsh plugin` 管理

完整列表见 [docs/FEATURE_zh.md](docs/FEATURE_zh.md)。

## 项目结构

```
mini-dsh/
├── Makefile                          # 任务自动化
├── scripts/
│   └── setup.sh                      # 一键安装脚本
├── minidsh/                          # Python 包
│   ├── __init__.py
│   ├── cordis/                       # 插件容器内核
│   ├── infrastructure/               # 启动、配置、bundle、profile、打包、tui
│   │   ├── boot/                     # CLI 入口 + 项目加载
│   │   ├── bundle/                   # Bundle 清单加载
│   │   ├── config/                   # Config / models.json / settings.json
│   │   ├── packaging/                # 插件发现（entry-points）
│   │   ├── profile/                  # Profile 覆盖链
│   │   └── tui/                      # pi-tui launcher + Node.js 前端
│   │       ├── app_pi_tui.py         # App 插件：spawn pi-tui 子进程
│   │       └── pi-tui/               # Node.js 前端（ACP 客户端）
│   ├── packages/
│   │   ├── core/                     # 共享库原语
│   │   ├── services/                 # 能力服务（20+ 能力）
│   │   └── tools/                    # 消费方工具（bash, read_file, web, lsp）
│   └── bundles/                      # 内置激活清单
├── tests/                            # 测试套件（pytest）
├── docs/                             # 设计文档与构建原则
└── pyproject.toml                    # 包元数据 & entry-points
```

## 快速开始

### 前置条件

- Python >= 3.11
- Node.js >= 18（安装脚本在 Linux/macOS 上自动安装）

### 1. 安装

```bash
git clone https://github.com/ChenYu1991ppak/Minidsh.git
cd Minidsh
make install
```

这会安装 Python 依赖（`pip install -e .`）、Node.js 依赖，并编译 pi-tui 前端。

### 2. 配置模型

创建 `~/.minidsh/models.json` 并填入你的 API key：

```bash
mkdir -p ~/.minidsh
```

`models.json` 示例：

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

> 格式说明：[docs/PRINCIPLES_zh.md §8](docs/PRINCIPLES_zh.md#8-配置规约)。

### 3. 启动 TUI

```bash
make tui                          # 启动 pi-tui TUI
make tui-fake                     # 免 API key 启动（假 LLM）
```

或直接运行：

```bash
minidsh --profile tui [./project] # pi-tui 前端
```

## 开发

```bash
make test       # 运行全部测试（python -m pytest）
make clean      # 清理编译产物与缓存
```

### 无需 Node.js 的运行方式

如果不需要 TUI 前端，可直接使用 ACP server：

```bash
minidsh --profile acp              # ACP JSON-RPC server（需 API key）
minidsh --profile acp-fake         # 免 API key 的 ACP server（假 LLM）
```

## 自定义 profile

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