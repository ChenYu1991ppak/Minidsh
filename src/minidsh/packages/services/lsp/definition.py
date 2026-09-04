"""lsp 能力定义：代码语义 seam（ctx.lsp）。

源码对应：
- ``LspOperation`` / ``LspPosition`` / ``LspRange`` / ``LspQueryRequest`` ↔ packages/lsp/lsp/src/types.ts
- ``LspProvider`` / ``LspService`` ↔ packages/lsp/lsp/src/index.ts（provider 注册表 + 按扩展名选择）
- ``LspError`` ↔ packages/lsp/lsp/src/index.ts（结构化错误码）

LspService 管理 provider 注册与按文件扩展名的选择，暴露四个语义操作：
``goToDefinition`` / ``findReferences`` / ``goToImplementation`` / ``hover``。
不暴露 JSON-RPC 逃生舱、进程/文档控制等协议细节。

[教学简化] 位置/范围用零基（对齐协议）；``LspQueryResult`` 用单一 dataclass + ``kind``
判别字段近似官方闭合联合（locations / hover 两分支）；不实现官方「provider id 与扩展名
原子预留 + fiber 作用域卸载」，disposer 直接同步移除。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from minidsh.cordis import CapabilityProvider

__all__ = [
    "LspOperation",
    "LspPosition",
    "LspRange",
    "LspQueryRequest",
    "LspProviderQuery",
    "LspLocation",
    "LspHover",
    "LspQueryResult",
    "LspProvider",
    "LspService",
    "LspError",
    "final_extension",
    "LSP_OPERATIONS",
]

# 四操作闭合联合
LspOperation = Literal["goToDefinition", "findReferences", "goToImplementation", "hover"]
LSP_OPERATIONS: tuple[str, ...] = ("goToDefinition", "findReferences", "goToImplementation", "hover")


# ---------------------------------------------------------------------------
# 坐标 / 请求 / 结果类型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LspPosition:
    """零基 UTF-16 光标坐标（对齐 LSP 协议）。"""

    line: int
    character: int


@dataclass(frozen=True)
class LspRange:
    """零基 UTF-16 半开区间 [start, end)。"""

    start: LspPosition
    end: LspPosition


@dataclass(frozen=True)
class LspQueryRequest:
    """调用方归一化查询：操作 + 文件 + 零基位置。"""

    operation: LspOperation
    filePath: str
    position: LspPosition


@dataclass(frozen=True)
class LspProviderQuery(LspQueryRequest):
    """provider 收到的请求：调用方请求 + seam 推导的 languageId。"""

    languageId: str = ""


@dataclass(frozen=True)
class LspLocation:
    """一个解析出的位置：文档 URI + 其内范围。"""

    uri: str
    range: LspRange | None = None


@dataclass(frozen=True)
class LspHover:
    """归一化 hover 内容；无 hover 时为 None（由结果的 hover 字段表达）。"""

    contents: str
    range: LspRange | None = None


@dataclass(frozen=True)
class LspQueryResult:
    """闭合结果：``kind='locations'`` 带 locations[]；``kind='hover'`` 带 hover（可 None）。"""

    kind: Literal["locations", "hover"]
    locations: list[LspLocation] = field(default_factory=list)
    hover: LspHover | None = None


# ---------------------------------------------------------------------------
# LspError
# ---------------------------------------------------------------------------


class LspError(Exception):
    """结构化 lsp 错误：code 为机器可路由的错误码。"""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Provider 接口
# ---------------------------------------------------------------------------


class LspProvider:
    """language-server 后端。注册到 ctx.lsp.registerProvider。

    子类须设 ``id`` 与 ``extensionToLanguage``（小写、带点扩展名 → language id）。
    """

    id: str = ""
    extensionToLanguage: dict[str, str] = {}

    def available(self) -> bool:
        """本地可用性检查（不得有网络/进程调用）。"""
        return True

    async def query(self, request: LspProviderQuery) -> LspQueryResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 扩展名归一化
# ---------------------------------------------------------------------------


def final_extension(file_path: str) -> str:
    """取文件最终扩展名：小写、带点（如 ``Foo.TS`` → ``.ts``）。

    无扩展名或前导点 dotfile（``.bashrc``）返回 ``''``；同时按 ``/`` 与 ``\\`` 切分。
    """
    last_slash = max(file_path.rfind("/"), file_path.rfind("\\"))
    base = file_path[last_slash + 1:] if last_slash >= 0 else file_path
    dot = base.rfind(".")
    if dot <= 0:
        return ""
    return base[dot:].lower()


_EXTENSION_PATTERN_OK = lambda ext: ext.startswith(".") and len(ext) > 1 and "/" not in ext and "\\" not in ext and "." not in ext[1:]


def _normalize_extension(ext: str) -> str:
    lower = ext.lower()
    return lower if lower.startswith(".") else f".{lower}"


# ---------------------------------------------------------------------------
# LspService
# ---------------------------------------------------------------------------


class LspService(CapabilityProvider):
    """ctx.lsp：provider 注册表 + 按扩展名选择执行四操作。

    构造即注册 ctx.lsp；``register_provider`` 原子预留 id 与扩展名，冲突即整体拒绝。
    """

    service_name = "lsp"

    def _init(self, ctx):
        self._provider_ids: set[str] = set()
        self._routes: dict[str, tuple[LspProvider, str]] = {}  # ext -> (provider, languageId)

    def register_provider(self, provider: LspProvider):
        """注册 provider：校验 + 冲突检查后才落库；返回 disposer。

        不合规（空 id / 无扩展名 / 非法扩展名 / 冲突）抛 ``LspError``，不落任何状态。
        """
        pid = provider.id
        if not pid or not pid.strip():
            raise LspError("an LSP provider id must be a non-empty string", "LSP_INVALID_PROVIDER")
        if pid in self._provider_ids:
            raise LspError(f'an LSP provider with id "{pid}" is already registered', "LSP_CONFLICT")

        entries = dict(provider.extensionToLanguage or {})
        if not entries:
            raise LspError(f'LSP provider "{pid}" registers no file extensions', "LSP_INVALID_PROVIDER")

        pending: dict[str, tuple[LspProvider, str]] = {}
        for raw_ext, language_id in entries.items():
            ext = _normalize_extension(raw_ext)
            if not _EXTENSION_PATTERN_OK(ext):
                raise LspError(f'LSP provider "{pid}" maps an invalid extension "{raw_ext}"', "LSP_INVALID_PROVIDER")
            if not language_id or not language_id.strip():
                raise LspError(f'LSP provider "{pid}" maps extension "{ext}" to an empty language id', "LSP_INVALID_PROVIDER")
            if ext in pending:
                raise LspError(f'LSP provider "{pid}" maps extension "{ext}" more than once', "LSP_INVALID_PROVIDER")
            pending[ext] = (provider, language_id)

        for ext in pending:
            if ext in self._routes:
                raise LspError(f'extension "{ext}" is already handled by another LSP provider', "LSP_CONFLICT")

        # 全部校验通过才落库
        self._provider_ids.add(pid)
        self._routes.update(pending)

        def dispose():
            self._provider_ids.discard(pid)
            for ext in pending:
                self._routes.pop(ext, None)

        return dispose

    async def query(self, request: LspQueryRequest) -> LspQueryResult:
        """按文件扩展名选 provider 执行查询；无匹配抛 ``LSP_UNAVAILABLE``。"""
        ext = final_extension(request.filePath)
        route = self._routes.get(ext)
        if route is None:
            raise LspError(f'no LSP provider handles "{request.filePath}"', "LSP_UNAVAILABLE")
        provider, language_id = route
        provider_request = LspProviderQuery(
            operation=request.operation,
            filePath=request.filePath,
            position=request.position,
            languageId=language_id,
        )
        return await provider.query(provider_request)