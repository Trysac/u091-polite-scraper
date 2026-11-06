# Architecture

## Purpose

`trysac-polite-scraper` is a small, dependency-free Python library that fetches web pages politely: RFC 9309 robots.txt, per-origin pacing, conditional caching, SSRF guards and size limits, plus HTML text extraction.

## Shape

```text
caller code --> polite_scraper (public API in __init__.py)
                    |
                    +-- HttpTransport (injected; default urllib without redirects)
                    +-- clock and sleep (injected; default time.monotonic and time.sleep)
```

- **Public API**: the names listed in `__all__` of `src/polite_scraper/__init__.py`. `polite_scraper.testing` holds test doubles.
- **Errors**: failures raise `ScraperError` with a stable `code`; invalid constructor arguments raise `ValueError`.
- **State**: `PoliteScraper` keeps in-memory LRU tables for robots policies, last request times per origin and cached pages.
- **I/O**: only the default transport touches the network; it is excluded from coverage.

## Quality contract

`scripts/check.py` is the single definition of the gates; `fabrica.json` tells the factory and CI how to run it. See [TESTING.md](TESTING.md).

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
