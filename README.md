# mini-dsh

**最小化 DeepSeek Harness（dsh）**：Python 忠実复刻官方 dsh 的工程骨架。

以 Cordis「一切皆插件」容器为内核，串起 agent-loop / tools / skills / subagent /
session 事件流 / LLM 适配 / compaction / token 计量，做到可运行、可观测、可追溯。

构建原则见 [doc/PRINCIPLES.md](doc/PRINCIPLES.md)，版本特性见 [doc/CHANGELOG-v1.md](doc/CHANGELOG-v1.md)。

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/ChenYu1991ppak/Minidsh.git
cd Minidsh

# 2. 安装
pip install -e . --no-build-isolation

# 3. 配置模型（必须）
mkdir -p ~/.minidsh
cat > ~/.minidsh/models.json << 'EOF'
{
  "models": [{
    "id": "deepseek-chat",
    "name": "DeepSeek V3",
    "vendor": "DeepSeek",
    "url": "https://api.deepseek.com",
    "apiKey": "$DEEPSEEK_API_KEY",
    "supportsToolCall": true,
    "supportsReasoning": true
  }],
  "availableModels": ["deepseek-chat"],
  "currentModel": "deepseek-chat"
}
EOF
chmod 600 ~/.minidsh/models.json
```

> 配置详情见 [doc/PRINCIPLES.md §8](doc/PRINCIPLES.md#8-配置规约)。

## 运行

```bash
# pi-tui 前端（终端交互，需 API key）
minidsh --profile tui [./project]

# 免 API key 测试（假 LLM 回放）
MINIDSH_ACP_PROFILE=acp-fake minidsh --profile tui [./project]

# Textual TUI（Python 进程内，中文终端/教学参考）
minidsh --profile tui-textual [./project]

# ACP server（供外部程序调用）
minidsh --profile acp [./project]
minidsh --profile acp-fake [./project]   # 免 API key

# 会话重放
minidsh replay <path/to/sessions.jsonl>

# 插件管理
minidsh plugin add <pkg>     # 安装第三方插件
minidsh plugin remove <name> # 移除
minidsh plugin ls            # 列举
```

## 前端

mini-dsh 有三个前端门面，经 `--profile` 选择：

| 命令 | 前端 | 说明 |
|---|---|---|
| `--profile tui` | pi-tui | Node.js 差分渲染终端，CSS 调色板，对齐官方 dsh-tui |
| `--profile tui-textual` | Textual | Python 进程内，中文终端/教学参考 |
| `--profile acp` | ACP server | JSON-RPC stdio，供外部程序调用 |

生态选型见 [docs/pi-tui.md](docs/pi-tui.md)。

## 配置

### Profile

`--profile <name>` 选择前端/后端组合。详细机制见 [doc/PRINCIPLES.md §7](doc/PRINCIPLES.md#7-bundle--profile-规约)。

内置 bundle（`src/minidsh/bundles/`）：

| Bundle | 内容 |
|---|---|
| `minidsh.base` | 默认后端（session/llm/tools/skills/subagent/compaction/…） |
| `minidsh.tui` | pi-tui 前端门面 |
| `minidsh.tui-textual` | Textual TUI 前端门面 |
| `minidsh.acp` | ACP server（需 API key） |
| `minidsh.acp-fake` | ACP server + 假 LLM（免 API key） |

自定义 profile（`~/.minidsh/profiles/my.yaml`）：

```yaml
bundles: [tui]          # 在 base 基础上叠加 tui 前端
plugins:                # 直接追加/覆盖插件
  - my-extra-plugin
remove:                 # 移除不需要的插件
  - minidsh.llm-openai
```

### 模型

`models.json` 配置模型列表。详见 [doc/PRINCIPLES.md §8](doc/PRINCIPLES.md#8-配置规约)。

## 测试

```bash
# 必须用 python -m pytest（裸 pytest 缺 tests 路径）
python -m pytest -q

# 当前：584 测试全绿
```

## 架构

```
minidsh --profile <name>
  ├─ launcher（cli.py）: 解析 --profile --patch --storage --session
  ├─ profile 覆盖链: 默认 base < 命名 < 项目 < 用户 < argv
  ├─ load_project: 装配 Context（entry-point 发现 + 插件激活）
  └─ app 插件: minidsh.app-* 前缀，接管进程
       ├─ minidsh.app-tui         → spawn pi-tui 前端
       ├─ minidsh.app-tui-textual → Textual TUI
       └─ minidsh.app-acp         → ACP JSON-RPC stdio
```

核心能力（`packages/services/`）：

| 服务 | 能力 | 官方对应 |
|---|---|---|
| `session` | append-only 事件日志 + 会话注册表 | `packages/core/session` |
| `loop` | react 循环驱动器（agent-loop） | `packages/core/agent-loop` |
| `llm` | OpenAI 兼容流式适配 + 软映射层 | `packages/llm` |
| `tools` | 工具注册表 + 守卫执行管线 | `packages/core/tools` |
| `tokenMeter` | 真实 token 计量（provider 回传） | `packages/llm/token-meter` |
| `compaction` | 上下文压缩（阈值触发 + 手动） | `packages/compaction` |
| `approval` | 工具审批（ask/never + 应答者瀑布） | `packages/interaction/user-approval` |
| `web` | Web 检索 seam（search/fetch 注册表） | `packages/web` |
| `acp` | ACP JSON-RPC stdio server | `packages/acp` |
| `skills` | 文件系统技能加载 | `packages/skill` |
| `subagent` | 进程内子代理委派 | `packages/subagent` |
| `persistence` | JSONL/SQLite 持久化 | `packages/session/session-persistence` |

## 未来工作

与官方 dsh 的对比，已实现与未实现：

### ✅ 已实现

| 官方能力 | mini-dsh 实现 |
|---|---|
| Cordis 插件容器 | `cordis/`（Context/Fiber/Service/事件/四态归一） |
| Agent loop + react | `loop/agent_loop.py`（turn 边界 + 流式 LLM + 工具执行） |
| 工具注册表 + 守卫管线 | `tool_runtime/runtime.py`（pre/post-execute + GuardRegistry） |
| LLM 适配 + 软映射 | `llm/openai.py` + `softmap.py`（四家模型差异收敛） |
| 思考模式五档 | `reasoningEffort` + reasoning-delta 流式 + 回传协议 |
| Session 事件流 | `session/event.py`（白名单 + frozen + surface/audit 分层） |
| 上下文压缩 | `compaction/`（prune/summarize 策略） |
| 工具审批 | `approval/`（ask/never + waterfall 应答者） |
| Web 检索 | `web/`（fetch_http + search 注册表） |
| 技能加载 | `skills/`（文件系统 SKILL.md） |
| 子代理委派 | `subagent/`（进程内） |
| 真实 token 用量 | `tokenMeter.record_usage`（provider 回传，非估算） |
| Session 持久化 | `persistence/`（JSONL + SQLite + 写后置） |
| 会话恢复 | `loop.resume` + `derive_messages` + CLI `--session` |
| 通用 launcher | `--profile` 选前端门面，`--patch` 覆盖层 |
| pi-tui 前端 | Node.js 差分渲染 + ACP 协议 + 工具卡片折叠 |
| Textual TUI | Python 进程内 + 转录视图 + 斜杠命令 |

### ⏳ P1（会话读面）

| 官方能力 | 说明 |
|---|---|
| `session-title` | LLM 自动生成标题（当前为确定性 fallback） |
| `session-query` | 会话全文搜索 |
| `feedback` | 消息反馈（点赞/点踩） |
| `attachment` | 图片附件上传 |
| `spill` | 大输出溢出文件 |
| `storage` | 结构化存储域 |

### ⏳ P2（产品广度）

| 官方能力 | 说明 |
|---|---|
| `plan` | 任务规划 + todo 面板 |
| `goal` | 目标追踪 |
| `todo` | 待办清单 |
| `commands` | 完整命令注册表 + ScopedLayers |
| `str-replace-editor` | 文件编辑器 |
| `fs-search` | 文件系统搜索（grep/glob） |
| `ask-user` | 用户提问工具 |
| `schedule` | 定时任务 |
| `hooks` | 生命周期钩子 |

### ⏳ P3（平台）

| 官方能力 | 说明 |
|---|---|
| `terminal` | PTY 终端工具 |
| `workflow` | 多 agent 编排 |
| `jobs` | 后台任务 |
| `code-runtime` | 代码沙箱 |
| `webhook` | Webhook 触发器 |
| `mcp` | MCP 协议支持 |
| `sdk` | SDK JSON-RPC（IDE 插件） |
| `identity` | 用户身份/SSO |
| `client` | Web 前端（React） |

详细构建原则、三角色规约、命名规约、测试规约见 [doc/PRINCIPLES.md](doc/PRINCIPLES.md)。