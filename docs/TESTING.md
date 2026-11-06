# Testing

## Running

```sh
uv run pytest --cov=polite_scraper   # tests with coverage report
uv run python scripts/check.py      # every gate, as CI and the factory run it
```

## Policy

- Branch coverage of `src/polite_scraper` must stay at or above 80 %; the gate fails below it.
- The default urllib transport is excluded from coverage (`# pragma: no cover`) because tests never touch the network.
- Tests exercise the public API (`import polite_scraper`) and assert observable effects: return values, raised exceptions and their codes.
- Tests are deterministic: they use `FakeTransport` and `FakeClock`, with no network, no wall clock and no dependence on test order.

## Layout

`tests/test_polite_scraper.py` covers the public API: robots.txt parsing and matching, host and URL guards, redirects, size and content-type limits, pacing and Crawl-Delay, the conditional cache with LRU eviction, and `extract_text`. Test doubles live in `src/polite_scraper/testing.py`.
