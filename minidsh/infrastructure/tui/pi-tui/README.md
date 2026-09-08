# mini-dsh pi-tui 前端

pi-tui 终端前端，经 ACP 协议驱动 mini-dsh agent。生态选型说明见
[`../../../../docs/pi-tui.md`](../../../../docs/pi-tui.md)。

## 运行

```bash
cd minidsh/infrastructure/tui/pi-tui
npm install
npm run build        # tsc → dist/
npm start ./project  # 在 ./project 下启动 ACP 前端
```

前端 spawn `minidsh --profile acp` 子进程，stdio 走 JSON-RPC 2.0 ndjson。

## 命令

| 键 | 动作 |
|---|---|
| 输入文本 + Enter | 发送消息（`session/prompt`） |
| `/exit` 或 `/quit` | 退出前端 + 关闭 ACP 子进程 |
| Ctrl+C | 取消当前 turn（`session/cancel`） |

## 结构

| 文件 | 职责 |
|---|---|
| `src/index.ts` | 主入口：pi-tui 组件树 + 输入循环 |
| `src/acp-client.ts` | ACP JSON-RPC client（spawn 子进程 + 响应路由） |
| `src/session-state.ts` | 本地会话投影（转录条目 / 工具调用 / token 用量） |

## 实现范围（教学简化）

- 转录按 user / assistant / thought / tool-call 四类渲染（无 Markdown 完整高亮）。
- 工具结果超 500 字截断（对齐 `output-retention` 的 head 展示）。
- 只做单会话；`/model`、`/new`、审批交互 UI 留待后续（ACP 已支持 `set_config_option`）。