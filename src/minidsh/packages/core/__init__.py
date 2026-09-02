"""packages/core：跨服务共享的「库原语」（非 cordis 服务）。

对齐官方 packages/core 里除 session/tools/agent/agent-loop/system-prompt/scope 之外，
唯一非服务包 scope 的定位：零依赖库，位于服务模块图之下，供服务去消费而不成环。
"""