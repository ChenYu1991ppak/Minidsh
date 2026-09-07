# mini-dsh

**最小化 DeepSeek Harness（dsh）**：用 Python 从零构建的 dsh 工程骨架。

## 存在的意义

1. **配合教学，逐机制对齐**：配套教学仓库 [deepseek-harness-anatomy](https://github.com/ChenYu1991ppak/deepseek-harness-anatomy)，本实现完全根据教学内容从 0 构建，每个能力/机制都能与官方 `packages/*/src` 对上号。
2. **Python 开发者自建 agent harness 的起点**：不同分支对应不同构建阶段，可直接作为模板分叉出你自己的 agent harness。

构建原则见 [doc/PRINCIPLES.md](doc/PRINCIPLES.md)。

## 运行

### 安装

```bash
git clone https://github.com/ChenYu1991ppak/Minidsh.git
cd Minidsh
pip install -e . --no-build-isolation

# 配置模型（必须）
mkdir -p ~/.minidsh
# models.json 内嵌 apiKey，见 doc/PRINCIPLES.md §8
```

### 启动 TUI

```bash
minidsh --profile tui [./project]          # pi-tui 前端（需 API key）
minidsh --profile tui-textual [./project]  # Textual TUI（中文终端/教学参考）
```

> 免 API key 测试：`MINIDSH_ACP_PROFILE=acp-fake minidsh --profile tui`

### 自定义 profile

`--profile <name>` 启动自定义 profile 或内置 bundle。详细编写方法见 [doc/PRINCIPLES.md §7](doc/PRINCIPLES.md#7-bundle--profile-规约)。

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