# mini-dsh 构建原则与约定

> 这是 mini-dsh 的**规则手册**：后续迭代改动时，先查这里，再动代码。
> 每条原则都源自已落地的实现，不是未实现的理想。与官方对不上的地方，
> 代码注释与本文都会标 `[教学简化]` 或 `[偏离]`。

---

## 1. 一句话定位

**mini-dsh 是用 Python 忠实复刻 DeepSeek Harness（dsh）的工程骨架**：
以 Cordis「一切皆插件」容器为内核，串起 agent-loop / tools / skills / subagent /
session 事件流 / LLM 适配 / compaction，做到可运行、可观测、可追溯。

- 对齐目标是官方 [`packages/*/src` + `docs/subsystems/*`]，机制名与逐章注释对齐教学仓 `deepseek-harness-anatomy/`（只读）。
- **忠实 > 精简**：先保证机制形态对（seam 三角色、事件流、提供方可替换），再谈实现难度。
- 参考仓库 `deepseek-harness-anatomy/` 是**只读**的独立 git 仓库，改动只发生在 `src/minidsh/` 与 `tests/`。

## 2. 世界观（三条铁律）

1. **一切皆插件**：能力、工具、观测、装配，全都是插件，经统一 `ctx.plugin` 装载。
2. **注册即效应**：`provide` / `register` / `ctx.effect` 都是可逆的——卸载即移除，fiber 卸载时逆序清理。
3. **能力三角色**：一个能力拆成「定义 / 提供方 / 消费方」三层（见 §5），这是 seam 可替换的根基。

**agent = model + harness**：loop 负责「要怎么跑」，llm 负责「这一句怎么说」，工具与提示节负责「能做什么」。

## 3. 内核约束（cordis/）

内核**同步、单线程**（spec §11-5）。LLM 流式是唯一异步面，由 loop 层用 asyncio 适配，内核不碰 asyncio。

| 实体 | 约定 | 说明 |
|---|---|---|
| `Context` | `provide/probe/service/has/inject/plugin/effect/emit/on/serial/waterfall/dispose` | `__getattr__` 只拦截缺失属性→服务表；服务注册一律走显式 `provide()`（决策 G6） |
| `Service` | 构造即注册 | 卸载时（fiber 逆序执行 `ctx.effect` 注册的 disposer）自动移除 |
| `Fiber` | PENDING/ACTIVE/UNLOADING/DISPOSED 四态 | 依赖服务被重新 `provide`/`dispose` 时「变化即重载」 |
| `normalize_plugin` | 四形态归一 → `Plugin(name, inject, factory, explicit_name)` | module / class / 带 apply 对象 / 函数 |
| 重名 | 显式 `name` 重复**抛 ValueError**；推导名重复只告警 | 在 `ctx.plugin` 注册时把关 |

**变化即重载**：fiber 对 `service/provide` / `service/dispose` 的订阅**不走 `ctx.effect`**（否则卸载时订阅被当 disposer 撤销，无法再重载），而是直接写监听器表，只在最终 `dispose()` 移除。

## 4. 目录职责（不可混淆）

```
src/minidsh/
├── cordis/                # 内核，独立（等价官方 @deepseek-ai/cordis）
│   └── capability.py      #   三角色抽象基类
├── infrastructure/        # 支撑：不是能力，是装配/配置/打包/前端
│   ├── boot/              #   cli（minidsh TUI 入口 / replay / plugin）+ load_project
│   ├── bundle/            #   Bundle / PluginRef / merge / build_context
│   ├── config/            #   Config/ModelSpec + resolve + files + providers
│   ├── packaging/         #   entry-point 发现 + plugin 命令
│   ├── profile/           #   resolve_profile 覆盖链
│   └── tui/               #   交互式前端（transcript 视图模型 / Textual App / bridge）
├── packages/
│   ├── core/               # 共享「库原语」（非 ctx 服务，官方 core/scope 的对应）
│   │   └── scope/          #   ScopeKey / Scope / ScopedLayers / createScope
│   ├── services/           # 提供 ctx 服务的能力（definition + providers/ + 辅助）
│   └── tools/              # 消费方工具（bash.py / read_file.py）
└── bundles/               # 激活清单 minidsh.base.yaml
```

**四个分区定位（勿混淆）**：

| 目录 | 定位 | 官方对应 |
|---|---|---|
| `cordis/` | 内核 | `@cordisjs/core` |
| `packages/core/` | **共享库原语（非服务）** | `packages/core/scope` |
| `packages/services/` | 提供 ctx 服务 | `packages/core/{session,tools,agent,agent-loop}`+各 `packages/*` |
| `packages/tools/` | 消费方工具 | `packages/*/tool-*` |

**两个「tools」彻底分家（易混点，勿再合并）**：

| 位置 | 是什么 |
|---|---|
| `packages/tools/` | **消费方工具插件**（module 形态，进清单，写 `ctx.tools` 注册表） |
| `packages/services/tool_runtime/` | **ctx.tools 服务**（ToolRuntime/ToolDefinition/ToolOutput） |
| 各 service 根下的 `catalog.py`/`task.py` | **造工具的工厂辅助**（被 provider 调用，不直接是插件） |

## 5. 能力三角色规约（建一个新能力的流程）

定义见 [cordis/capability.py](../src/minidsh/cordis/capability.py)：

- `CapabilityDefinition`：**纯契约**——只声明类属性 `service_name` + 接口方法，不自注册。定义放 `services/<x>/definition.py`。
- `CapabilityProvider`：`Definition + Service`，**构造即注册**到 `service_name`，初始化覆写 `_init(ctx, *args, **kw)`（不要手写 `super().__init__(ctx, "x")`）。放 `services/<x>/providers/<name>.py`。
- `CapabilityConsumer`：**不做基类**，保持 module 形态；只提供 `assert_valid(inject, service_name)` 校验（`inject` 必须含 `tools` 与被消费的 `service_name`）。消费者（进清单）放 `packages/tools/*.py`。

**三层职责铁律（Never）**：

| 禁止 | 原因 |
|---|---|
| definition 注册服务 | 注册是 Provider 的职责 |
| consumer import provider 类 | 消费者只依赖 definition + `ctx.<service_name>`，provider 可替换 |
| provider 直接注册工具 | 工具是 Consumer 经 `ctx.tools.register` 写的 |
| 给无「模型面」的能力硬建 tool | 无模型消费面的能力（session/compaction/…）不硬套三角色 |

## 6. 插件规范

**四形态**（[normalize_plugin](../src/minidsh/cordis/plugin.py) 归一）：

```python
# 1) module（本项目消费方工具/服务 provider 的主流形态）
name = "minidsh.tool-bash"
inject = ["tools", "shell", "config"]
def apply(ctx): ...

# 2) class（CapabilityProvider 子类，构造即注册）
# 3) 带 apply 方法的对象
# 4) 函数
```

**发现**：entry-point 组 `minidsh.plugins`（`pyproject.toml`），条目 `name = 插件名`，`value = 可 import 模块`。
内置与第三方插件**同走 entry-point 发现**（`entry_point_resolver`，无 registry 短路）。
新增一个内置插件 = ① 写模块 ② 在 pyproject 加 entry-point ③（如需默认激活）加进 `bundles/minidsh.base.yaml`。

## 7. bundle / profile 规约

- **无「manifest」这个词**（已消除）——只有 bundle（声明式激活清单）和 profile（覆盖链）。
- `Bundle(name, plugins, remove)`；bundle 文件 = 顶层 `plugins:` 列表（可有 `remove:`）。
- `profile` 文件 = 三键 `bundles:` / `plugins:` / `remove:`。
- **覆盖链**（后覆盖前）：
  `默认 [minidsh.base] < 命名 profile < 项目 <project>/.minidsh/profile.yaml < 用户 ~/.minidsh/profile.yaml < argv（--profile 给路径时）`
- `--profile` 合一：文件存在 → 当 argv 覆盖路径；否则 → 当命名 profile 名。
- provider 选择走清单：CLI `--storage jsonl|sqlite` 转成「移除未选中的 provider、追加选中的」，**不走进 provider 内部 if 分支**。

## 8. 配置规约

两个文件（对齐 CodeBuddy）：
- `models.json`——模型配置，每模型内嵌 `apiKey`（**敏感**，写盘 `chmod 600`，永不提交进 git）。
- `settings.json`——harness 设置（storage / compaction / tools 白名单），非密。

路径：用户级 `~/.minidsh/`（或 `$MINIDSH_HOME`），项目级 `<project>/.minidsh/`。
优先级：项目级覆盖用户级；模型列表**拼接**（同名 id 项目赢），settings 键**项覆盖**。
当前模型：`currentModel` > `availableModels` 首位。

**铁律**：无 provider 抽象、**无环境变量**、无密钥外泄——apiKey 只从 `models.json` 读。

## 9. 工具规约

- `ToolDefinition(name, description, parameters[OpenAI JSON Schema], execute[async], output[ToolOutput(schema, render)])`
- `ToolOutput.schema` 声明**规范值**类型、`render(args, value)->str` 转成给模型的内容。
- 执行管线（[runtime.py](../src/minidsh/packages/services/tool_runtime/runtime.py)）：
  `pre-execute 瀑布 → 单调 guard → execute → post-execute 瀑布`，产出 `ToolResult` 并广播 `tools/result`。
- 参数取**规范值**（`execute` 收 dict），JSON 反序列化由 loop 做（`_parse_arguments`）。
- 工具名沿用官方（`bash`/`read_file`/`skill-catalog`/`task`）。
- 工具白名单：consumer 经 `inject=["config"]` 读 `allowed_tools`，`None`=全开，列表不含则跳过注册。

## 9-b. LLM 适配与思考模式（软映射层）

**seam**：`llm/definition.py` 定义 `LlmRuntime.stream` + `Chunk`（内核/loop 不 import openai
类型）；`llm/providers/openai.py` 是唯一 import openai 的地方。将来加 anthropic = 新增 provider。

**思考五档与软映射**（[softmap.py](../src/minidsh/packages/services/llm/softmap.py)）：
- 统一枚举 `reasoningEffort`：`off / minimal / low / medium / high`（默认 `medium`），
  存 `ModelSpec.reasoning_effort`，非法档位解析期抛 `ValueError`（fail fast）。
- **软映射层是纯函数、只认 model id 家族（前缀）**，无视 vendor 字段（对齐 claw-code）。
  四家差异全收敛在四个函数：

  | 函数 | 作用 |
  |---|---|
  | `is_reasoning_model(id)` | 推理/思维链模型 → 请求剥离 temperature/top_p/penalties（固定采样，传了会被 400 拒收） |
  | `requires_reasoning_history(id)` | 必须在多轮/工具调用里回传上一轮 `reasoning_content` 的家族（deepseek-v4 / kimi-k3 / kimi-k2.7） |
  | `reasoning_effort_map(id, effort)` | 五档 → 各家真实值（就近归并：DS medium→high、K3 high→max 等） |
  | `thinking_optin(id, effort)` | 需要 `thinking` / `enable_thinking` 开关的家族（DeepSeek/Kimi K2.6/Qwen） |

- **温度语义**：非推理模型透传；推理模型剥离（官方「思考模式不支持 temperature」）。
- **推理强度档位诚实降级**：DeepSeek/Kimi 无 `medium` 档、K3 无 `off`、GPT o-series 不逐字回传思考——
  softmap 里如实归并/忽略，不伪造。

**流式思考字段**：统一 `delta.reasoning_content` → `Chunk(kind="reasoning-delta")` → 会话事件
`reasoning-chunk`（白名单 + 持久化）。GPT o-series 不回传思考流，故无思考可显示（API 限制，非缺实现）。

**回传协议（模型切换安全）**：reasoning 是**持久历史数据**，存进 `self.messages` 的 assistant
消息 `reasoning_content` 旁路字段；wire 序列化每次按**当前 model** 现算决定 echo/strip。所以
`/model` 同会话来回切，reasoning 始终能按当前模型要求回传。纯文本无工具轮可不回传。

## 10. 会话事件契约

- `SessionEventType` 白名单（[event.py](../src/minidsh/packages/services/session/event.py)）：
  `user-message / assistant-chunk / assistant-message / reasoning-chunk / tool-call /
  tool-result / model-change / skill-loaded / subagent-spawn / subagent-result /
  compaction / error`。
- **新增事件类型 = 在白名单枚举加一个成员**（非破坏性），未知类型构造期即拒绝（杜绝脏数据）。
- `SessionEvent` frozen（对齐官方 deepFreeze 的不可变语义）；payload 契约「append 后不改」。
- **刷盘边界 = `assistant-message`**（v1「一条回复」边界），另有 `session/flush` 事件作显式屏障。

## 10-b. TUI 前端（观察者，不碰 core 机制）

- **定位**：`infrastructure/tui/` 是「可观测性」的前端，不是 `packages/services/` 能力。
- **只读观察者**：只订阅 `session/event` 渲染，不新增事件、不改 loop/tools；一律 `post_message`
  异步转发，**绝不**在同一事件循环里起第二个 `asyncio.run`。
- **视图模型与渲染解耦**：`transcript.py`（`fold` 纯函数，事件 → turn 树）不 import Textual、
  可脱离终端单测；`app.py`/`bridge.py` 才碰 UI。
- **交互命令**（斜杠）：`/exit`、`/model <id>`（切模型，同会话续聊，跨所有 models.json 模型）、
  `/thinking <档位>`（切思考强度）；状态栏显示「模型(档位)」。`replay`/`plugin` 仍是独立 CLI 子命令。
- 无 `run` 子命令：`minidsh [dir]`（dir 缺省 cwd）直接启动 TUI。

## 11. 命名规约（汇总表）

| 项 | 约定 | 例 |
|---|---|---|
| 插件名（entry-point 键 + module `name`） | `minidsh.<小写连字符>` | `minidsh.tool-bash` / `minidsh.persistence-sqlite` |
| 服务名（`service_name`） | camelCase，对齐官方 `ctx.<name>` | `systemPrompt` / `agent_loop` / `sessionPersistence` |
| 事件名 | `domain/action` 或 kebab-case | `tools/change` / `assistant-message` |
| 目录/模块 | 小写下划线 | `tool_runtime` / `read_file.py` |

## 12. 对齐纪律

- **逐机制标注源码对应**：模块 docstring 与关键行写 `↔ index.ts:296`、`对应 ch02`、`对应 packages/core/agent-loop`。
- **偏离处标 `[教学简化]`**：真实版做不到/刻意裁掉的（deepFreeze、六态 fiber、zstd 压缩、定时 flush、per-agent scope……），必须在注释声明。
- **契约对象名对齐官方**：`ToolDefinition/ToolExecution/ToolResult/Chunk/SubagentError/…` 与官方同构。

## 13. 测试规约

- 栈：pytest + pytest-asyncio（`asyncio_mode=auto`）+ pytest-cov。`pythonpath=["src"]`。
- **基线：全绿 + 高覆盖**（当前 338 tests / 93%）。改动外部行为必须同绿。
- **不用 StubLlm**：LLM 测试用 `tests/helpers/` 的 `make_fake_llm`（脚本化回放）+ `openai_fake`（假 client）。内核/loop 从不 import openai 类型。
  - 脚本化 client 支持 `{"reasoning": "...", "text": "..."}` 轮次 → 产 `reasoning-delta` + `text-delta`。
- **执行世界装配**：shell-local 依赖 subprocess，测试里用 `tests/helpers/world.py` 的 `plug_execution_world(ctx)` 一次插好 subprocess→shell→fs，再 plugin 工具。
- **bwrap 测试 skip 门控**：sandbox 用 `pytest.mark.skipif(shutil.which("bwrap") is None)`，无 bwrap 环境跳过（不假装 full）。
- **TUI 测试**：视图模型（`fold`）纯单测；交互命令用 `App.run_test()`（Pilot）异步断言（斜杠命令 reconfigure / 状态栏刷新）。
- **隔离 `MINIDSH_HOME`**：`tests/conftest.py` autouse fixture 把用户配置目录指向 tmp（防止读到真实 apiKey）。
- 注意：**必须用 `python -m pytest` 跑**（裸 `pytest` 缺 `tests` 包路径，collect 会报 `No module named 'tests.helpers'`）。改了 pyproject 的 entry-point 后要 `pip install -e . --no-build-isolation` 才会刷新发现缓存。

## 14. 版本 / 发布 / 敏感信息

- 版本号**单一真相源**：`minidsh/__init__.py` 的 `__version__`（pyproject 经 `attr` 读它）。
- 打包：setuptools，**只发布 `src/` 库**（`packages.find where=["src"]`）；tests/examples/doc 不随库分发，但 doc/ 应进 git（见下）。
- **敏感信息**：`apiKey` 明文只在 `models.json`（`chmod 600` + gitignore）；`.env`/`*.key` 永不提交。

---

## 附：迭代检查清单（改代码前过一遍）

- [ ] 新能力是否拆成 definition / provider / consumer 三层？consumer 是否经 `ctx.tools.register` 而非提供新服务？
- [ ] 新增插件是否走了 entry-point + bundle 激活，而非硬编码 registry？
- [ ] 有没有引入「manifest」措辞 / 环境变量 / provider 抽象？（都违反铁律）
- [ ] 新旧两个「tools」是否各归其位（`packages/tools/` vs `tool_runtime/` vs service 根辅助）？
- [ ] 事件类型是否进了 `SessionEventType` 白名单？
- [ ] 新模型的思考强度是否走了 `softmap` 软映射（而非在 provider 里散落 if）？温度剥离对 reasoning 模型是否正确？
- [ ] reasoning 回传是否按「持久历史 + 每次按当前 model 现算 echo/strip」，而非 load 时定死？
- [ ] TUI 改动是否只读 session/event、没碰 core 机制？
- [ ] 偏离官方处是否标了 `[教学简化]`？关键做来源标注 `↔`？
- [ ] 是否用 `python -m pytest` 跑，全绿 + 覆盖不降？