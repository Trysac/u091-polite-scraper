# Project record

## Objective

Provide a small, dependency-free Python library that fetches web pages while following RFC 9309 robots.txt rules, pacing requests per origin, caching pages conditionally, refusing internal network targets and bounding response sizes.

## Scope

- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: JavaScript execution, DNS resolution or checks, sitemaps, concurrency, cookies, and anything that needs runtime dependencies or I/O without an accepted ADR.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 145758 / 307087 |
| Hours (human) | pending measurement |
| Cost (USD) | 1.5950 |

## Factory run u091 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2722 | 128000 | 0 | 4246 | 0.6431 |
| generation | claude-sonnet-5-5 | yes | 2722 | 128000 | 0 | 4246 | 0.6431 |
| generation | claude-sonnet-5-5 | yes | 2722 | 46146 | 0 | 4246 | 0.2339 |
| audit | claude-sonnet-5-5 | no | 0 | 0 | 0 | 0 | 0.0000 |
| docs | claude-haiku-5-5 | no | 124854 | 4941 | 0 | 0 | 0.0748 |

Total: $1.5950. Prices: Anthropic list prices.
