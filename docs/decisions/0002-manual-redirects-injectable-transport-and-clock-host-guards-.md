# Manual redirects, injectable transport and clock, host guards without DNS

Status: accepted (generated, pending human review)

## Context

A small scraping helper must obey robots.txt (RFC 9309), pace requests, avoid SSRF and stay deterministic in tests, without becoming a framework.

## Decision

Use one PoliteScraper class over an injectable HttpTransport that never follows redirects; the scraper follows them itself, validating scheme and host and checking robots.txt on every hop. Time and sleep are injected. Hosts are checked syntactically (IP literals, numeric forms, localhost) and DNS is never resolved. State is bounded by LRU tables.

## Consequences

Behaviour is deterministic and testable with FakeTransport and FakeClock, and redirects cannot bypass guards. DNS rebinding and names resolving to private addresses are not defended; users must pin resolution in a custom transport. Unreachable robots results are not cached, so they are retried on the next fetch.
