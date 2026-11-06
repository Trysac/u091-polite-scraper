# Threat model

`polite_scraper` fetches untrusted URLs on behalf of a caller.

## Defended

- Every hop, including `robots.txt` and redirects, must be http or https without userinfo.
- Hosts are lowercased and stripped of one trailing dot, then refused when they are `localhost`,
  `*.localhost`, a private, loopback, link-local, reserved, multicast or unspecified IP literal
  (IPv4-mapped IPv6 is unwrapped), or a numeric host that is not canonical dotted-quad.
- Redirects are followed manually (at most `max_redirects`, and robots is checked on each hop);
  bodies are limited to `max_bytes`; no `Accept-Encoding` is sent, so there is no decompression bomb.
- Robots data is capped at 512000 bytes; caches and pacing tables are bounded and evict the
  least recently used entries.
- Error messages and events never contain query strings, paths or bodies.

## Not defended

DNS names that resolve to private addresses and DNS rebinding: DNS is never resolved. Pin the
resolution in a custom `HttpTransport` when that matters.

Out of scope: JavaScript, sitemaps, concurrency, cookies.
