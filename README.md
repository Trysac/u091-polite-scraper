# polite-scraper

[![PyPI version](https://img.shields.io/pypi/v/trysac-polite-scraper)](https://pypi.org/project/trysac-polite-scraper/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-polite-scraper)](LICENSE)
[![CI](https://github.com/Trysac/u091-polite-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u091-polite-scraper/actions/workflows/ci.yml)

Fetch web pages politely with RFC 9309 robots.txt, per-host pacing, conditional caching, SSRF guards, size limits and text extraction

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-polite-scraper
# or
uv add trysac-polite-scraper
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import polite_scraper

# normalize() trims surrounding whitespace and lower-cases the text.
print(polite_scraper.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    polite_scraper.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
