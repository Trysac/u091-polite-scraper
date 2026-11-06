# Security notes

## Threat model

`trysac-polite-scraper` performs HTTP GET requests through an injectable transport. The threats below are the ones the code addresses, with their limits.

### Defended

- **Disallowed paths**: every fetch checks the origin's robots.txt under RFC 9309 (longest match, Allow wins ties, percent-encoding normalised, `/robots.txt` always allowed). Robots are checked again on every redirect hop.
- **Internal targets (SSRF)**: every hop, including robots.txt, must use http or https without userinfo. Hosts `localhost` and `*.localhost` are refused, as are IP literals that are private, loopback, link-local, reserved, multicast or unspecified (IPv4-mapped IPv6 is unwrapped). Numeric hosts that are not canonical dotted-quad (decimal, hex, octal, short forms) are refused. Disable with `allow_private=True`.
- **Redirect loops and chains**: at most `max_redirects` hops (five by default; robots redirects at least five).
- **Oversized responses**: the transport reads at most `max_bytes + 1` bytes; larger bodies raise `response_too_large`. Only 512,000 bytes of robots.txt are parsed.
- **Hammering hosts**: requests to one origin are spaced by `max(min_delay, Crawl-Delay)`; Crawl-Delay above `max_crawl_delay` raises an error.
- **Unbounded memory**: page cache is bounded by entries and bytes; robots and pacing tables hold at most 10,000 origins.
- **Credentials in messages**: error messages never include query strings; `on_event` receives only event, origin and status.

### Not defended

- **DNS names resolving to private addresses, and DNS rebinding**: DNS is not resolved, so a public-looking name that points at an internal address is not refused. Pin resolution in a custom `HttpTransport` if this matters.
- **Compressed responses**: the default transport sends no Accept-Encoding, but a custom transport's decompression is not checked.
- **Content safety**: returned HTML and text are not sanitised; `extract_text` only drops script, style, noscript, template, nav and footer content.
- **Authentication, cookies and TLS policy**: not handled by the library; the default transport uses the standard urllib defaults.

## Supply chain

No runtime dependencies. Dependabot runs weekly, GitHub Actions are pinned to major versions, and workflow permissions are minimal. `gitleaks` runs locally and in CI, and `.env` files are git-ignored.

## Publishing

Releases are published to PyPI with trusted publishing (OIDC) when available, never with a long-lived token stored in the repository.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).
