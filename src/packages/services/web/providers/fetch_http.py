"""web-fetch-http provider：匿名公共 HTTP(S) 抓取（真 provider，对齐官方）。

源码对应：
- ``HttpFetchProvider`` ↔ packages/web/web-fetch-http/src/provider.ts
- 策略函数 ↔ packages/web/web-fetch-http/src/policy.ts（纯函数，无网络）

安全抓取契约（对齐官方）：
- 无凭据：URL 内不允许 username/password；请求不带浏览器 cookie。
- 仅 HTTP/HTTPS scheme；URL 长度有界。
- DNS 解析阶段拒绝私有/环回/链路本地等非公共 IP（``WEB_BLOCKED_URL``）。
- 仅跟随**同源**重定向，跳数有界（``WEB_REDIRECT_BLOCKED``）。
- 有界读：响应体超 ``max_response_bytes`` 截断（``truncated=True``）。
- 仅文本：按 Content-Type 分类为 html/text，二进制拒绝（``WEB_UNSUPPORTED_CONTENT_TYPE``）。
- 显式 User-Agent（非浏览器伪装）。
- 非 2xx 为**结果**非错误（statusCode 是资源状态的一部分）。

[教学简化] 不实现官方 ``publicHttpNetwork`` 的「DNS 解析后 pin 到已验证地址」的连接钉扎
（Python httpx 无等价低层钩子）；不实现 AbortSignal 取消；DNS 检查在 fetch 前一次性做。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urljoin

import httpx

from ..definition import (
    WebFetchProvider,
    WebFetchRequest,
    WebFetchResult,
    WebFetchBody,
    WebError,
)

__all__ = [
    "HttpFetchProvider",
    "LOCAL_FETCH_PROVIDER_ID",
    "DEFAULT_USER_AGENT",
    "WEB_FETCH_MAX_URL_LENGTH",
    "validate_fetch_url",
    "is_same_origin",
    "classify_content_type",
    "is_blocked_ip",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

LOCAL_FETCH_PROVIDER_ID = "http"

# 显式产品 User-Agent，非浏览器伪装
DEFAULT_USER_AGENT = "mini-dsh/0.1 (+https://github.com/mini-dsh)"

WEB_FETCH_MAX_URL_LENGTH = 2048


# ---------------------------------------------------------------------------
# 策略函数（纯，无网络；对齐 policy.ts）
# ---------------------------------------------------------------------------


def validate_fetch_url(url: str):
    """解析并校验请求 URL：长度有界 + 仅 http/https + 无内嵌凭据。

    返回解析后的 ``ParseResult``；不合规抛 ``WebError``。
    """
    if len(url) > WEB_FETCH_MAX_URL_LENGTH:
        raise WebError(
            f"URL exceeds the maximum length of {WEB_FETCH_MAX_URL_LENGTH}",
            "WEB_INVALID_URL",
        )
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise WebError(f"invalid URL: {url}", "WEB_INVALID_URL") from exc
    if parsed.scheme not in ("http", "https"):
        raise WebError(
            f'unsupported URL scheme "{parsed.scheme}" (only http and https are allowed)',
            "WEB_INVALID_URL",
        )
    if parsed.username or parsed.password:
        raise WebError("credentials in URLs are not allowed", "WEB_BLOCKED_URL")
    if not parsed.hostname:
        raise WebError(f"URL has no hostname: {url}", "WEB_INVALID_URL")
    return parsed


def is_same_origin(a, b) -> bool:
    """两 URL 同源 = scheme + hostname + port 全同。跨源重定向被拒。"""
    return (a.scheme == b.scheme and a.hostname == b.hostname and a.port == b.port)


def classify_content_type(content_type: str | None) -> str | None:
    """把 Content-Type 归一为可解码的 body kind；不支持（二进制）返回 None。

    text/html 与 application/xhtml+xml → 'html'；其余 text/* 与若干结构化文本 → 'text'。
    """
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    if mime.startswith("text/"):
        return "text"
    if mime in ("application/json", "application/xml") or mime.endswith("+json") or mime.endswith("+xml"):
        return "text"
    return None


def is_blocked_ip(ip_str: str) -> bool:
    """判断一个 IP 是否应被拒（非公共可路由地址）。

    私有、环回、链路本地、多播、未指定、保留段一律拒——防止 SSRF 触达内网服务。
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # 无法解析视为拒
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def resolve_public_addresses(hostname: str) -> list[str]:
    """DNS 解析 hostname，返回全部地址；解析失败抛 ``WEB_PROVIDER_ERROR``。

    [教学简化] 私有/非公共地址的拒绝由 ``HttpFetchProvider`` 统一经 ``is_blocked_ip``
    把关（纵深防御）；本函数只做纯解析。官方在 connect 层钉扎已验证地址，此处一次性解析。
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise WebError(f"DNS resolution failed for {hostname}", "WEB_PROVIDER_ERROR") from exc

    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise WebError(f"no addresses resolved for {hostname}", "WEB_PROVIDER_ERROR")
    return list(addrs)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class HttpFetchProvider(WebFetchProvider):
    """匿名公共 HTTP(S) 抓取 provider（id="http"）。"""

    def __init__(
        self,
        max_response_bytes: int = 5_000_000,
        max_body_chars: int = 100_000,
        timeout_s: float = 30.0,
        max_redirects: int = 5,
        user_agent: str = DEFAULT_USER_AGENT,
        resolve=resolve_public_addresses,
        client_factory=None,
    ):
        super().__init__(LOCAL_FETCH_PROVIDER_ID)
        self._max_response_bytes = max_response_bytes
        self._max_body_chars = max_body_chars
        self._timeout_s = timeout_s
        self._max_redirects = max_redirects
        self._user_agent = user_agent
        self._resolve = resolve
        # 可注入的客户端工厂（测试替身）；缺省 httpx.AsyncClient
        self._client_factory = client_factory or httpx.AsyncClient

    def available(self) -> bool:
        return True  # 匿名公共抓取，无凭据可查

    async def fetch(self, request: WebFetchRequest) -> WebFetchResult:
        parsed = validate_fetch_url(request.url)
        # DNS 阶段拒私有目标（SSRF 防护）：解析后逐个地址把关
        addresses = self._resolve(parsed.hostname)
        for addr in addresses:
            if is_blocked_ip(addr):
                raise WebError(
                    f"URL resolves to a blocked non-public address ({addr})",
                    "WEB_BLOCKED_URL",
                )

        headers = {"user-agent": self._user_agent,
                   "accept": "text/html,application/xhtml+xml,text/*;q=0.9,application/json;q=0.8"}

        current = parsed
        redirects = 0
        async with self._client_factory(follow_redirects=False, timeout=self._timeout_s) as client:
            while True:
                try:
                    resp = await client.get(current.geturl(), headers=headers)
                except httpx.TimeoutException as exc:
                    raise WebError("web fetch timed out", "WEB_FETCH_TIMEOUT") from exc
                except httpx.HTTPError as exc:
                    raise WebError(f"web fetch failed: {exc}", "WEB_PROVIDER_ERROR") from exc

                if resp.is_redirect:
                    if redirects >= self._max_redirects:
                        raise WebError(
                            f"exceeded the maximum of {self._max_redirects} redirects",
                            "WEB_REDIRECT_BLOCKED",
                        )
                    location = resp.headers.get("location")
                    if location is None:
                        raise WebError(
                            f"redirect response (HTTP {resp.status_code}) without a Location header",
                            "WEB_PROVIDER_ERROR",
                        )
                    target = validate_fetch_url(urljoin(current.geturl(), location))
                    if not is_same_origin(target, current):
                        raise WebError(
                            f"cross-origin redirect to {target.scheme}://{target.netloc} is not "
                            "followed automatically; retry against that URL directly",
                            "WEB_REDIRECT_BLOCKED",
                        )
                    current = target
                    redirects += 1
                    continue

                return self._build_result(resp, current)

    def _build_result(self, resp: httpx.Response, final_url) -> WebFetchResult:
        kind = classify_content_type(resp.headers.get("content-type"))
        if kind is None:
            raise WebError(
                f'unsupported content type "{resp.headers.get("content-type") or "unknown"}"',
                "WEB_UNSUPPORTED_CONTENT_TYPE",
            )

        # 有界读：超 max_response_bytes 截断
        raw = resp.content
        truncated = False
        if len(raw) > self._max_response_bytes:
            raw = raw[: self._max_response_bytes]
            truncated = True

        text = resp.text if len(raw) == len(resp.content) else raw.decode("utf-8", errors="replace")
        if len(text) > self._max_body_chars:
            text = text[: self._max_body_chars]
            truncated = True

        return WebFetchResult(
            url=final_url.geturl(),
            statusCode=resp.status_code,
            body=WebFetchBody(kind=kind, content=text),
            truncated=truncated,
        )


# ---------------------------------------------------------------------------
# base 插件入口：minidsh.web-fetch（注入 web，注册 HttpFetchProvider）
# ---------------------------------------------------------------------------

name = "minidsh.web-fetch"
inject = ["web"]


def apply(ctx):
    ctx.web.register_fetch_provider(HttpFetchProvider())