# polite-scraper

[![PyPI version](https://img.shields.io/pypi/v/trysac-polite-scraper)](https://pypi.org/project/trysac-polite-scraper/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-polite-scraper)](LICENSE)
[![CI](https://github.com/Trysac/u091-polite-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u091-polite-scraper/actions/workflows/ci.yml)

Fetch web pages politely with RFC 9309 robots.txt, per-host pacing, conditional caching, SSRF guards, size limits and text extraction.

## Problem

Scripts that read a few web pages often ignore robots.txt, request hosts in quick succession, refetch unchanged pages and can be pointed at internal addresses. Scrapy handles politeness but is a full framework, while requests plus BeautifulSoup provides none of these checks. polite-scraper is a single small class with an injectable transport and clock, so the rules are enforced and remain deterministic in tests.

## Install

```sh
pip install trysac-polite-scraper
# or
uv add trysac-polite-scraper
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from polite_scraper import PoliteScraper, extract_text

scraper = PoliteScraper(user_agent="MyBot/1.0", min_delay=1.0)
page = scraper.fetch("https://example.com/")
print(page.from_cache, page.final_url)
print(extract_text(page.text, base_url=page.final_url).title)
```

## Public API

Module `polite_scraper` exports six names: `PoliteScraper`, `Page`, `Response`, `HttpTransport`, `RobotsPolicy`, `ScraperError`, `extract_text`, `ExtractedText`, and `__version__`.

- `PoliteScraper(transport=None, *, user_agent, clock=time.monotonic, sleep=time.sleep, min_delay=1.0, max_crawl_delay=30.0, max_bytes=2_000_000, max_redirects=5, robots_ttl=86400.0, max_cache_entries=1000, max_cache_bytes=50_000_000, allow_private=False, on_event=None)`. `fetch(url) -> Page`.
- `Page(url, final_url, status, text, from_cache)`.
- `RobotsPolicy.parse(text, product_token)`, `allowed(path) -> bool`, `crawl_delay`.
- `extract_text(html, *, base_url=None, max_chars=1_000_000) -> ExtractedText(title, text, links)`.
- `HttpTransport` is a protocol with `get(url, headers, timeout, max_bytes) -> Response`.
- `polite_scraper.testing` provides `FakeTransport` and `FakeClock`.

### Errors

`ScraperError.code` is one of `disallowed_by_robots`, `blocked_host`, `unsupported_scheme`, `invalid_url`, `too_many_redirects`, `response_too_large`, `unsupported_content_type`, `http_error`, `fetch_failed`, `crawl_delay_too_long`. Messages never include query strings.

### Limits and options

- robots.txt: only the first 512,000 bytes are parsed; 404 allows everything; 5xx, 429 and network errors disallow the origin; up to five robots redirects are followed.
- Crawl-Delay is honoured up to `max_crawl_delay`; larger values raise `crawl_delay_too_long`.
- Pacing sleeps `max(min_delay, crawl_delay)` between requests to one origin, robots.txt included.
- Page cache is LRU, bounded by `max_cache_entries` and `max_cache_bytes`; robots and pacing tables hold 10,000 origins each.
- Accepted content types: text/html, application/xhtml+xml, text/plain.
- Private, loopback, link-local, reserved, multicast and unspecified IP literals are refused unless `allow_private=True`. DNS names are not resolved, so this is not a defence against DNS rebinding.
- `on_event` receives `event`, `origin` and `status` only.

## Why not Scrapy

Scrapy is a full crawling framework with its own project layout and scheduler. polite-scraper covers only single-page politeness for scripts, in one class.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model, including what is not defended.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
