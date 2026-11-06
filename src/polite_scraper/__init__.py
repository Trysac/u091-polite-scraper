"""Fetch web pages politely: RFC 9309 robots.txt, pacing, conditional caching and SSRF guards."""

from __future__ import annotations

import codecs
import ipaddress
import logging
import math
import re
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import SplitResult, quote, urldefrag, urljoin, urlsplit

__all__ = [
    "ExtractedText",
    "HttpTransport",
    "Page",
    "PoliteScraper",
    "Response",
    "RobotsPolicy",
    "ScraperError",
    "__version__",
    "extract_text",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

_ROBOTS_MAX_BYTES = 512_000
_MAX_ORIGINS = 10_000
_MAX_URL = 8192
_MAX_HTML_CHARS = 10_000_000
_MAX_LINKS = 10_000
_TIMEOUT = 30.0
_REDIRECTS = (301, 302, 303, 307, 308)
_ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9"
_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
_NUM = re.compile(r"\d+|0[xX][0-9a-fA-F]*")
_CHARSET = re.compile(r"charset\s*=\s*['\x22]?([\w.:-]+)", re.IGNORECASE)
_META = re.compile(rb"<meta[^>]{0,200}?charset\s*=\s*['\x22]?([\w.:-]+)", re.IGNORECASE)
_FATAL = frozenset({"blocked_host", "unsupported_scheme", "invalid_url"})

ErrorCode = Literal[
    "disallowed_by_robots",
    "blocked_host",
    "unsupported_scheme",
    "invalid_url",
    "too_many_redirects",
    "response_too_large",
    "unsupported_content_type",
    "http_error",
    "fetch_failed",
    "crawl_delay_too_long",
]


class ScraperError(Exception):
    """Base error of the library; ``code`` is stable and machine readable."""

    def __init__(self, code: ErrorCode, message: str, status: int | None = None) -> None:
        super().__init__(message[:200])
        self.code: ErrorCode = code
        self.status = status


@dataclass(frozen=True)
class Response:
    """A raw HTTP response returned by a transport."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str


class HttpTransport(Protocol):
    """Performs a single GET without following redirects and without decompression."""

    def get(self, url: str, headers: Mapping[str, str], timeout: float, max_bytes: int) -> Response:
        """Return the response, reading at most ``max_bytes + 1`` body bytes."""
        ...


@dataclass(frozen=True)
class Page:
    """A fetched page."""

    url: str
    final_url: str
    status: int
    text: str
    from_cache: bool


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class _UrllibTransport:
    """Default transport: urllib, no redirects, no Accept-Encoding."""

    def get(  # pragma: no cover - needs the network
        self, url: str, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> Response:
        opener = urllib.request.build_opener(_NoRedirect)
        opener.addheaders = list(headers.items())
        try:
            with opener.open(url, timeout=timeout) as resp:
                return Response(
                    resp.status, dict(resp.headers.items()), resp.read(max_bytes + 1), url
                )
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(max_bytes + 1)
            finally:
                exc.close()
            return Response(exc.code, dict(exc.headers.items()), body, url)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    low = name.lower()
    for key, value in headers.items():
        if key.lower() == low:
            return value
    return None


def _blocked() -> ScraperError:
    return ScraperError("blocked_host", "host is not allowed")


def _guard_host(host: str) -> None:
    if host == "localhost" or host.endswith(".localhost"):
        raise _blocked()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if all(_NUM.fullmatch(label) for label in host.split(".")):
            raise _blocked() from None
        return
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        raise _blocked()


def _check_url(url: str, allow_private: bool) -> tuple[SplitResult, str]:
    if not url or len(url) > _MAX_URL or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ScraperError("invalid_url", "URL is empty, too long or has control characters")
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ScraperError("invalid_url", "URL could not be parsed") from exc
    if not scheme:
        raise ScraperError("invalid_url", "URL has no scheme")
    if scheme not in ("http", "https"):
        raise ScraperError("unsupported_scheme", "only http and https are supported")
    if not host or "@" in parts.netloc:
        raise ScraperError("invalid_url", "URL has no host or contains userinfo")
    if host.endswith("."):
        host = host[:-1]
    if not host:
        raise ScraperError("invalid_url", "URL has no host")
    if not allow_private:
        _guard_host(host)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return parts, f"{scheme}://{netloc}"


def _target(parts: SplitResult) -> str:
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def _normalize(value: str) -> str:
    upper = re.sub(r"%[0-9a-fA-F]{2}", lambda m: m.group(0).upper(), value)
    return quote(upper, safe="/%*$?&=:@!~'()+,;-._[]#")


def _match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    parts = pattern.split("*")
    if len(parts) == 1:
        return path == pattern if anchored else path.startswith(pattern)
    if not path.startswith(parts[0]):
        return False
    pos = len(parts[0])
    for mid in parts[1:-1]:
        found = path.find(mid, pos)
        if found < 0:
            return False
        pos = found + len(mid)
    last = parts[-1]
    if anchored:
        return len(path) - len(last) >= pos and path.endswith(last)
    return path.find(last, pos) >= 0


@dataclass(frozen=True)
class RobotsPolicy:
    """Parsed robots.txt rules for one product token (RFC 9309)."""

    rules: tuple[tuple[bool, str], ...] = ()
    crawl_delay: float | None = None

    @classmethod
    def parse(cls, text: str, product_token: str) -> RobotsPolicy:
        """Parse at most 512000 bytes of ``text`` for ``product_token``."""
        token = product_token.split("/")[0].strip().lower()
        data = text.encode("utf-8")[:_ROBOTS_MAX_BYTES].decode("utf-8", errors="ignore")
        data = data.lstrip("\ufeff")
        groups: list[tuple[list[str], list[tuple[bool, str]], list[float]]] = []
        in_agents = False
        for raw in re.split(r"\r\n|\n|\r", data):
            line = raw.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if not in_agents:
                    groups.append(([], [], []))
                    in_agents = True
                groups[-1][0].append(value.lower())
            elif key in ("allow", "disallow", "crawl-delay"):
                in_agents = False
                if not groups:
                    continue
                if key == "crawl-delay":
                    try:
                        delay = float(value)
                    except ValueError:
                        continue
                    if math.isfinite(delay) and delay >= 0:
                        groups[-1][2].append(delay)
                elif value:
                    groups[-1][1].append((key == "allow", _normalize(value)))
        chosen = [g for g in groups if token in g[0]] or [g for g in groups if "*" in g[0]]
        rules = tuple(rule for g in chosen for rule in g[1])
        delays = [d for g in chosen for d in g[2]]
        return cls(rules, delays[0] if delays else None)

    def allowed(self, path: str) -> bool:
        """Return whether ``path`` (with optional query) may be fetched."""
        norm = _normalize(path or "/")
        if not norm.startswith("/"):
            norm = "/" + norm
        if norm == "/robots.txt":
            return True
        best = -1
        verdict = True
        for allow, pattern in self.rules:
            if _match(pattern, norm):
                size = len(pattern)
                if size > best or (size == best and allow):
                    best = size
                    verdict = allow
        return verdict


_ALLOW_ALL = RobotsPolicy()
_DENY_ALL = RobotsPolicy(rules=((False, "/"),))


@dataclass(frozen=True)
class ExtractedText:
    """Readable text, title and http(s) links of an HTML document."""

    title: str
    text: str
    links: tuple[str, ...]


_SKIP = frozenset({"script", "style", "noscript", "template", "nav", "footer"})
_BLOCK = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "main"}
    | {"h1", "h2", "h3", "h4", "h5", "h6"}
)


class _TextParser(HTMLParser):
    def __init__(self, base_url: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.links: list[str] = []
        self.skip = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self._link(value.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in _BLOCK and not self.skip:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        (self.title_parts if self.in_title else self.parts).append(data)

    def _link(self, href: str) -> None:
        try:
            target = urljoin(self.base, href) if self.base else href
            scheme = urlsplit(target).scheme.lower()
        except ValueError:
            return
        if (
            scheme in ("http", "https")
            and target not in self.links
            and len(self.links) < _MAX_LINKS
        ):
            self.links.append(target)


def extract_text(
    html: str, *, base_url: str | None = None, max_chars: int = 1_000_000
) -> ExtractedText:
    """Extract title, text and http(s) links.

    Drops script, style, noscript, template, nav and footer content.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(html) > _MAX_HTML_CHARS:
        raise ScraperError("response_too_large", "HTML document is too large")
    parser = _TextParser(base_url)
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    text = "\n".join(line for line in lines if line)[:max_chars]
    title = " ".join("".join(parser.title_parts).split())
    return ExtractedText(title, text, tuple(parser.links))


def _decode(body: bytes, content_type: str) -> str:
    match = _CHARSET.search(content_type)
    name: str | None = match.group(1) if match else None
    if name is None:
        meta = _META.search(body[:2048])
        name = meta.group(1).decode("ascii", "replace") if meta else None
    encoding = "utf-8"
    if name:
        try:
            encoding = codecs.lookup(name).name
        except LookupError:
            encoding = "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


@dataclass
class _Entry:
    final_url: str
    status: int
    text: str
    etag: str | None
    last_modified: str | None
    size: int


class PoliteScraper:
    """Fetch pages while honouring robots.txt, pacing, caching and network guards."""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        user_agent: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_delay: float = 1.0,
        max_crawl_delay: float = 30.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        robots_ttl: float = 86400.0,
        max_cache_entries: int = 1000,
        max_cache_bytes: int = 50_000_000,
        allow_private: bool = False,
        on_event: Callable[[Mapping[str, object]], None] | None = None,
    ) -> None:
        if not user_agent.strip() or any(ord(c) < 32 or ord(c) == 127 for c in user_agent):
            raise ValueError("user_agent must be non-empty without control characters")
        self._transport: HttpTransport = transport if transport is not None else _UrllibTransport()
        self._ua = user_agent
        self._token = user_agent.split("/")[0].strip()
        self._clock = clock
        self._sleep = sleep
        self._min_delay = min_delay
        self._max_crawl_delay = max_crawl_delay
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._robots_ttl = robots_ttl
        self._max_entries = max_cache_entries
        self._max_cache_bytes = max_cache_bytes
        self._allow_private = allow_private
        self._on_event = on_event
        self._robots_cache: OrderedDict[str, tuple[float, RobotsPolicy]] = OrderedDict()
        self._last: OrderedDict[str, float] = OrderedDict()
        self._cache: OrderedDict[str, _Entry] = OrderedDict()
        self._cache_total = 0

    def _emit(self, event: str, origin: str, status: int | None) -> None:
        logger.debug("%s %s %s", event, origin, status)
        if self._on_event is not None:
            self._on_event({"event": event, "origin": origin, "status": status})

    def _pace(self, origin: str, delay: float | None) -> None:
        wait = max(self._min_delay, delay or 0.0)
        last = self._last.get(origin)
        if last is not None:
            remaining = wait - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[origin] = self._clock()
        self._last.move_to_end(origin)
        while len(self._last) > _MAX_ORIGINS:
            self._last.popitem(last=False)

    def _policy(self, origin: str) -> RobotsPolicy:
        now = self._clock()
        hit = self._robots_cache.get(origin)
        if hit is not None and now - hit[0] < self._robots_ttl:
            self._robots_cache.move_to_end(origin)
            return hit[1]
        self._robots_cache.pop(origin, None)
        headers = {"User-Agent": self._ua, "Accept": "text/plain"}
        try:
            resp, _ = self._request(origin + "/robots.txt", headers, robots=True)
        except ScraperError as exc:
            if exc.code in _FATAL:
                raise
            self._emit("robots_unreachable", origin, None)
            return _DENY_ALL
        status = resp.status
        if 200 <= status < 300:
            text = resp.body[:_ROBOTS_MAX_BYTES].decode("utf-8", errors="replace")
            policy = RobotsPolicy.parse(text, self._token)
        elif 400 <= status < 500 and status != 429:
            policy = _ALLOW_ALL
        else:
            self._emit("robots_unreachable", origin, status)
            return _DENY_ALL
        self._robots_cache[origin] = (now, policy)
        while len(self._robots_cache) > _MAX_ORIGINS:
            self._robots_cache.popitem(last=False)
        return policy

    def _request(
        self, url: str, headers: Mapping[str, str], *, robots: bool
    ) -> tuple[Response, str]:
        limit = max(5, self._max_redirects) if robots else self._max_redirects
        current = url
        for hop in range(limit + 1):
            parts, origin = _check_url(current, self._allow_private)
            delay: float | None = None
            if not robots:
                policy = self._policy(origin)
                if not policy.allowed(_target(parts)):
                    self._emit("disallowed", origin, None)
                    raise ScraperError(
                        "disallowed_by_robots", f"robots.txt of {origin} disallows this URL"
                    )
                delay = policy.crawl_delay
                if delay is not None and delay > self._max_crawl_delay:
                    raise ScraperError(
                        "crawl_delay_too_long", f"Crawl-delay of {origin} is too long"
                    )
            self._pace(origin, delay)
            try:
                resp = self._transport.get(current, headers, _TIMEOUT, self._max_bytes)
            except ScraperError:
                raise
            except Exception as exc:
                raise ScraperError("fetch_failed", f"request to {origin} failed") from exc
            self._emit("request", origin, resp.status)
            if not robots and len(resp.body) > self._max_bytes:
                raise ScraperError("response_too_large", f"response from {origin} is too large")
            location = _header(resp.headers, "location")
            if resp.status in _REDIRECTS and location:
                if hop >= limit:
                    raise ScraperError("too_many_redirects", f"too many redirects from {origin}")
                if len(location) > _MAX_URL:
                    raise ScraperError("invalid_url", "redirect location is too long")
                current = urldefrag(urljoin(current, location)).url
                continue
            return resp, current
        raise ScraperError("too_many_redirects", "too many redirects")  # pragma: no cover

    def _store(self, key: str, entry: _Entry) -> None:
        old = self._cache.pop(key, None)
        if old is not None:
            self._cache_total -= old.size
        if entry.size > self._max_cache_bytes:
            return
        self._cache[key] = entry
        self._cache_total += entry.size
        while self._cache and (
            len(self._cache) > self._max_entries or self._cache_total > self._max_cache_bytes
        ):
            _, evicted = self._cache.popitem(last=False)
            self._cache_total -= evicted.size

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` politely and return the decoded page."""
        key = urldefrag(url).url
        _check_url(key, self._allow_private)
        cached = self._cache.get(key)
        headers = {"User-Agent": self._ua, "Accept": _ACCEPT}
        if cached is not None:
            if cached.etag:
                headers["If-None-Match"] = cached.etag
            if cached.last_modified:
                headers["If-Modified-Since"] = cached.last_modified
        resp, final = self._request(key, headers, robots=False)
        if resp.status == 304 and cached is not None:
            self._cache.move_to_end(key)
            self._emit("cache_hit", _check_url(final, True)[1], 304)
            return Page(key, cached.final_url, cached.status, cached.text, True)
        if not 200 <= resp.status < 300:
            raise ScraperError(
                "http_error", f"server answered with status {resp.status}", resp.status
            )
        content_type = _header(resp.headers, "content-type") or ""
        if content_type.split(";")[0].strip().lower() not in _TYPES:
            raise ScraperError(
                "unsupported_content_type", "content type is not supported", resp.status
            )
        text = _decode(resp.body, content_type)
        etag = _header(resp.headers, "etag")
        modified = _header(resp.headers, "last-modified")
        if etag or modified:
            self._store(key, _Entry(final, resp.status, text, etag, modified, len(resp.body)))
        return Page(key, final, resp.status, text, False)
