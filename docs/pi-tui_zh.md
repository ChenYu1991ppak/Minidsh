# pi-tui 生态选型

[English](pi-tui.md) | 中文

## 为什么选择 pi-tui

mini-dsh 有两条 TUI 前端线：

| 前端 | 技术栈 | 形态 | 适用场景 |
|---|---|---|---|
| `tui-textual` | Python + Textual | 进程内 cordis 插件 | 中文终端、教学参考、单 Python 进程部署 |
| `pi-tui` | TypeScript + `@earendil-works/pi-tui` | 独立 Node.js 进程, ACP 协议 | 对齐官方 dsh-tui 生态、软件开发终端 |

## 决策依据

1. **官方选型**：`@deepseek-ai/dsh-tui`（1993 行 index.ts）以 `@earendil-works/pi-tui` 为核心渲染库，
   作者 mitsuhiko/badlogic 是终端工具领域资深开发者（pygments/insta/pixi 等）。该库是官方的
   「terminals-as-first-class」实现路径。

2. **差分渲染**：pi-tui 的 `TuiMainScreen` 只更新变化的行（differential rendering），
   天然不卡在 79KB 大文本上——与 Textual 的全文 Rich Text 排版形成互补。

3. **进程隔离**：pi-tui 前端经 ACP stdio 协议与 Python 后端通信，互不阻塞。
   Python 端跑 agent/session/tools，Node 端只管终端渲染+输入，职责清晰。

4. **生态对齐**：`@narumitw/pi-tui-kit`（Declarative UI flows）等第三方扩展
   已形成 pi-tui 组件生态；后续可复用现有扩展而非写新组件。

## 架构

```
┌─────────────────────────────────────────────────────┐
│ 终端（用户）                                          │
├─────────────────────────────────────────────────────┤
│ pi-tui 前端 (Node.js)                                │
│  ├─ acp-client.ts  ── spawn minidsh --profile acp   │
│  ├─ session-state.ts ── 本地会话投影                  │
│  └─ index.ts         ── pi-tui 组件树                │
├─────────────────────────────────────────────────────┤
│ ACP JSON-RPC stdio (ndjson, 每行一个 JSON 对象)       │
├─────────────────────────────────────────────────────┤
│ mini-dsh Python 后端                                  │
│  ├─ acp-server  ── 接收 JSON-RPC, 驱动 agent loop    │
│  ├─ agent-loop  ── ReactLoopAgent                    │
│  └─ session/llm/tools ── 内核能力                     │
└─────────────────────────────────────────────────────┘
```

## 运行

```bash
# 1. 安装前端依赖
cd frontends/pi-tui && npm install && npm run build

# 2. 启动（需 Python 后端已安装 minidsh）
cd /path/to/project && npx tsx /path/to/frontends/pi-tui/src/index.ts

# 2b. 或经 launcher（后续）
minidsh --profile tui   # 自动 spawn pi-tui 前端
```

## 测试

pi-tui 前端目前无自动测试（需真实 TTY 环境）。Python 侧 ACP 协议已覆盖 18 个测试
（`tests/tools/test_acp.py`），`minidsh --profile acp-fake` 提供免 API key 的 ACP 服务端。

## 参考

- [@earendil-works/pi-tui@0.85.0](https://www.npmjs.com/package/@earendil-works/pi-tui) — npm 包
- [pi-tui README](https://github.com/earendil-works/pi) — 源码仓库
- [Toad](https://batrachian.ai) — pi-tui 生态的思考型 AI 编码终端
- 官方 dsh-tui（已删除, commit `10bb9cbf4a`）— 1993 行 index.ts, 833 行 transcript.ts, 328 行 theme.ts

## 与官方 dsh-tui 的渲染对比

| 维度 | 官方 dsh-tui（已删） | mini-dsh pi-tui 前端 |
|---|---|---|
| 转录模型 | 单条有序 timeline（append-origin） | ✅ 同样的单条有序 `items`，工具卡片在消息之间内联渲染 |
| 工具卡片 | `ToolCardComponent` 三段折叠（hidden/collapsed/expanded） | ✅ 同样的三段折叠（Ctrl+O 循环） |
| 折叠预览 | `preview(body, maxOutputLines)` 前 N 行 + `… +N lines` 提示 | ✅ 前 6 行预览 + `… +N lines (Ctrl+O to expand)` |
| 卡片头 | `○/● Tool / <name>` 环标记 + 状态色 | ✅ `○/● Tool / <name>` + warning/success/error 状态色 |
| 输出上限 | `maxToolOutputLines`（可配置） | ✅ `TOOL_PREVIEW_LINES = 6`（编译期常量） |
| 思考渲染 | 可选显示 + italic dim | ⚠ 折叠为 200 字符 + dim（无展开/收起热键） |
| 状态色 | palette：dim/accent/success/warning/error/code | ⚠ 前五色 + ANSI 转义，无独立 Palette 类型/6 色 code 区分 |
| token 用量 | `tokenMeter` 实时底部栏 | ⚠ `usage` 字段有，但 ACP 未映射 `usage_update`，缺顶部栏动态刷新 |
| diff 卡片 | `renderDiff` 增删行着色 | ❌ 未实现（无 `diff` 工具的 presentation） |
| Markdown 渲染 | `Markdown` 组件（代码高亮/表格/链接） | ⚠ 纯文本 wrap（无代码块着色） |

## 已知差距（按优先级）

1. **token 用量不刷新**：ACP server 未把 `tokenMeter.measure()` 映射为 `usage_update`，前端顶部栏 `usage` 恒空。
2. **Markdown 无着色**：assistant 回复是纯文本，代码块/表格/链接未用 `Markdown` 组件渲染。
3. **工具输出截断值硬编码**：`TOOL_PREVIEW_LINES`/`MAX_TOOL_RESULT_CHARS` 应走配置。
4. **trailing output 拖动选择**：官方 body 行无前缀（拖选只复制工具原文），本版有 2 空格缩进。