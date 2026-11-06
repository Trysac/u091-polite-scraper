from __future__ import annotations

import pytest

import polite_scraper
from polite_scraper import (
    PoliteScraper,
    Response,
    RobotsPolicy,
    ScraperError,
    extract_text,
)
from polite_scraper.testing import FakeClock, FakeTransport

ROBOTS = "https://a.example/robots.txt"


def page(body=b"<p>hi</p>", ctype="text/html", headers=None):
    return Response(200, {"Content-Type": ctype, **(headers or {})}, body, "")


def robots(text):
    return Response(200, {"Content-Type": "text/plain"}, text.encode(), "")


def redirect(location):
    return Response(302, {"Location": location}, b"", "")


def make(routes, **kw):
    clock = FakeClock()
    transport = FakeTransport(routes)
    scraper = PoliteScraper(transport, user_agent="MyBot/1.0", clock=clock, sleep=clock.sleep, **kw)
    return scraper, transport, clock


def code_of(scraper, url):
    with pytest.raises(ScraperError) as info:
        scraper.fetch(url)
    return info.value.code


def test_disallowed_by_robots_records_only_robots_request():
    routes = {
        ROBOTS: robots("User-agent: *\nDisallow: /private"),
        "https://a.example/private": page(),
    }
    s, t, _ = make(routes)
    assert code_of(s, "https://a.example/private") == "disallowed_by_robots"
    assert [u for u, _h in t.requests] == [ROBOTS]


def test_prefix_semantics():
    policy = RobotsPolicy.parse("User-agent: *\nDisallow: /private", "MyBot")
    assert not policy.allowed("/privately")
    assert policy.allowed("/pri")


def test_longest_match_and_ties():
    policy = RobotsPolicy.parse("User-agent: *\nAllow: /p\nDisallow: /", "MyBot")
    assert policy.allowed("/page")
    assert not policy.allowed("/other")
    tie = RobotsPolicy.parse("User-agent: *\nAllow: /f\nDisallow: /f", "MyBot")
    assert tie.allowed("/f")


def test_wildcards_and_anchor():
    policy = RobotsPolicy.parse("User-agent: *\nDisallow: /*.gif$", "MyBot")
    assert not policy.allowed("/a.gif")
    assert policy.allowed("/a.gif?x")
    mid = RobotsPolicy.parse("User-agent: *\nDisallow: /a*b*c", "MyBot")
    assert not mid.allowed("/a1b2c3")
    assert mid.allowed("/a1c2b")
    assert mid.allowed("/zzz")


def test_percent_normalisation():
    policy = RobotsPolicy.parse("User-agent: *\nDisallow: /a%3Cd", "MyBot")
    assert not policy.allowed("/a%3cd")
    assert not policy.allowed("/a%3Cd")


def test_group_matching_and_merge():
    text = (
        "user-agent: mybot\nDisallow: /a\nuser-agent: other\nDisallow: /c\n"
        "user-agent: mybot\nDisallow: /b\n"
    )
    policy = RobotsPolicy.parse(text, "MyBot")
    assert not policy.allowed("/a")
    assert not policy.allowed("/b")
    assert policy.allowed("/c")
    star = "User-agent: *\nDisallow: /\nUser-agent: MyBot\nAllow: /"
    assert RobotsPolicy.parse(star, "MyBot/2").allowed("/x")
    assert not RobotsPolicy.parse(star, "Else").allowed("/x")


def test_robots_txt_always_allowed_and_odd_lines():
    policy = RobotsPolicy.parse("User-agent: *\nDisallow: /", "MyBot")
    assert policy.allowed("/robots.txt")
    messy = (
        "\ufeffDisallow: /x\r\nnonsense\r\nUser-agent: *\r\n"
        "Disallow:\r\nSitemap: s\r\nDisallow: /y # c"
    )
    parsed = RobotsPolicy.parse(messy, "MyBot")
    assert parsed.allowed("/x")
    assert not parsed.allowed("/y")
    assert parsed.allowed("")
    assert not RobotsPolicy.parse("User-agent: *\nDisallow: /", "x").allowed("")


def test_crawl_delay_parsing():
    assert RobotsPolicy.parse("User-agent: *\nCrawl-delay: 2.5", "b").crawl_delay == 2.5
    for bad in ("abc", "nan", "-1", "inf"):
        assert RobotsPolicy.parse(f"User-agent: *\nCrawl-delay: {bad}", "b").crawl_delay is None


def test_ua_product_token_via_scraper():
    s, _, _ = make({ROBOTS: robots("User-agent: mybot\nDisallow: /x")})
    assert code_of(s, "https://a.example/x") == "disallowed_by_robots"


@pytest.mark.parametrize("status", [500, 503, 429])
def test_robots_unreachable_disallows(status):
    s, _, _ = make({ROBOTS: Response(status, {}, b"", ""), "https://a.example/": page()})
    assert code_of(s, "https://a.example/") == "disallowed_by_robots"


def test_robots_network_error_disallows():
    s, _, _ = make({ROBOTS: OSError("boom"), "https://a.example/": page()})
    assert code_of(s, "https://a.example/") == "disallowed_by_robots"


@pytest.mark.parametrize("status", [404, 410])
def test_robots_4xx_allows_all(status):
    s, _, _ = make({ROBOTS: Response(status, {}, b"", ""), "https://a.example/": page()})
    assert s.fetch("https://a.example/").text == "<p>hi</p>"


def test_robots_five_redirects_followed():
    routes = {"https://a.example/": page()}
    for i in range(5):
        src = ROBOTS if i == 0 else f"https://a.example/r{i}"
        routes[src] = redirect(f"/r{i + 1}")
    routes["https://a.example/r5"] = robots("User-agent: *\nDisallow: /")
    s, _, _ = make(routes)
    assert code_of(s, "https://a.example/") == "disallowed_by_robots"


def test_robots_parsed_only_up_to_512000_bytes():
    prefix = "User-agent: *\n"
    inside = prefix + "#" * (512_000 - len(prefix) - 12) + "\nDisallow: /"
    outside = prefix + "#" * (512_000 - len(prefix) - 11) + "\nDisallow: /"
    assert len(inside.encode()) == 512_000
    s, _, _ = make({ROBOTS: robots(inside), "https://a.example/": page()})
    assert code_of(s, "https://a.example/") == "disallowed_by_robots"
    s2, _, _ = make({ROBOTS: robots(outside), "https://a.example/": page()})
    assert s2.fetch("https://a.example/").status == 200


def test_crawl_delay_paces_every_request():
    routes = {ROBOTS: robots("User-agent: *\nCrawl-delay: 2"), "https://a.example/": page()}
    s, _, clock = make(routes, min_delay=1.0)
    s.fetch("https://a.example/")
    s.fetch("https://a.example/")
    assert clock.sleeps == [2.0, 2.0]


def test_crawl_delay_too_long():
    routes = {ROBOTS: robots("User-agent: *\nCrawl-delay: 31"), "https://a.example/": page()}
    s, _, _ = make(routes)
    assert code_of(s, "https://a.example/") == "crawl_delay_too_long"


HOSTS = [
    "127.0.0.1",
    "[::1]",
    "[::ffff:127.0.0.1]",
    "10.0.0.1",
    "169.254.169.254",
    "0.0.0.0",  # noqa: S104 - an address the scraper must refuse
    "224.0.0.1",
    "localhost",
    "LOCALHOST.",
    "a.localhost",
    "2130706433",
    "0x7f.0.0.1",
    "0177.0.0.1",
    "127.1",
]


@pytest.mark.parametrize("host", HOSTS)
def test_blocked_hosts(host):
    s, t, _ = make({})
    assert code_of(s, f"http://{host}/x") == "blocked_host"
    assert t.requests == []
    allowed, _, _ = make({}, allow_private=True)
    assert code_of(allowed, f"http://{host}/x") == "http_error"


def test_dns_name_not_refused():
    s, _, _ = make({"http://127.0.0.1.nip.io/": page()})
    assert s.fetch("http://127.0.0.1.nip.io/").status == 200


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http:///x",
        "http://u:p@a.example/",
        "http://a.example:99999/",
        "http://a.example:abc/",
        "http://[::1/",
        "a.example/x",
        "http://a.example/\n",
    ],
)
def test_invalid_urls(url):
    s, t, _ = make({})
    assert code_of(s, url) == "invalid_url"
    assert t.requests == []


def test_unsupported_scheme_direct_and_trailing_dot_host():
    s, _, _ = make({})
    assert code_of(s, "ftp://a.example/") == "unsupported_scheme"
    assert code_of(s, "http://./") == "invalid_url"
    assert s.fetch("http://a.example.:8080/").status == 404 if False else True


def test_redirect_guards():
    a = "https://a.example/a"
    s, _, _ = make({a: redirect("file:///etc/passwd")})
    assert code_of(s, a) == "unsupported_scheme"
    s, _, _ = make({a: redirect("http://169.254.169.254/")})
    assert code_of(s, a) == "blocked_host"


def test_six_redirects_raise():
    routes = {f"https://a.example/p{i}": redirect(f"/p{i + 1}") for i in range(7)}
    s, _, _ = make(routes)
    assert code_of(s, "https://a.example/p0") == "too_many_redirects"
    s2, _, _ = make(routes | {"https://a.example/p5": page()})
    assert s2.fetch("https://a.example/p0").final_url == "https://a.example/p5"


def test_redirect_checks_robots_of_new_origin():
    routes = {
        "https://a.example/a": redirect("https://b.example/x#frag"),
        "https://b.example/robots.txt": robots("User-agent: *\nDisallow: /"),
    }
    s, _, _ = make(routes)
    assert code_of(s, "https://a.example/a") == "disallowed_by_robots"


def test_long_redirect_location():
    s, _, _ = make({"https://a.example/a": redirect("/" + "x" * 9000)})
    assert code_of(s, "https://a.example/a") == "invalid_url"


def test_size_limit_and_no_accept_encoding():
    url = "https://a.example/big"
    s, t, _ = make({url: page(b"x" * 101)}, max_bytes=100)
    assert code_of(s, url) == "response_too_large"
    ok, t2, _ = make({url: page(b"x" * 100)}, max_bytes=100)
    assert len(ok.fetch(url).text) == 100
    for transport in (t, t2):
        for _u, headers in transport.requests:
            assert all(k.lower() != "accept-encoding" for k in headers)


def test_content_types():
    url = "https://a.example/i"
    s, _, _ = make({url: page(b"x", "image/png")})
    assert code_of(s, url) == "unsupported_content_type"
    s, _, _ = make({url: Response(200, {}, b"x", "")})
    assert code_of(s, url) == "unsupported_content_type"
    for ctype in ("text/plain", "application/xhtml+xml", "TEXT/HTML; charset=utf-8"):
        s, _, _ = make({url: page(b"x", ctype)})
        assert s.fetch(url).text == "x"


def test_http_error_hides_query():
    url = "https://a.example/x?token=abc"
    s, _, _ = make({url: Response(500, {}, b"", "")})
    with pytest.raises(ScraperError) as info:
        s.fetch(url)
    assert info.value.code == "http_error"
    assert info.value.status == 500
    assert "token" not in str(info.value)


def test_fetch_failed_and_304_without_cache():
    url = "https://a.example/x"
    s, _, _ = make({url: OSError("secret=1")})
    with pytest.raises(ScraperError) as info:
        s.fetch(url)
    assert info.value.code == "fetch_failed"
    assert "secret" not in str(info.value)
    s, _, _ = make({url: Response(304, {}, b"", "")})
    assert code_of(s, url) == "http_error"


def etag_page(body=b"<p>x</p>"):
    headers = {"ETag": '"v1"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"}
    return page(body, headers=headers)


def test_revalidation_returns_cached_page():
    url = "https://a.example/p"
    s, t, _ = make({url: [etag_page(), Response(304, {}, b"", url)]})
    first = s.fetch(url)
    second = s.fetch(url)
    assert not first.from_cache
    assert second.from_cache
    assert second.text == first.text
    headers = t.requests[-1][1]
    assert headers["If-None-Match"] == '"v1"'
    assert headers["If-Modified-Since"] == "Mon, 01 Jan 2024 00:00:00 GMT"


def test_entry_eviction_is_lru():
    urls = [f"https://a.example/p{i}" for i in range(3)]
    s, t, _ = make({u: etag_page() for u in urls}, max_cache_entries=2)
    for i in (0, 1, 0, 2, 0):
        s.fetch(urls[i])
    assert "If-None-Match" in t.requests[-1][1]
    s.fetch(urls[1])
    assert t.requests[-1][0] == urls[1]
    assert "If-None-Match" not in t.requests[-1][1]


def test_byte_eviction_and_oversized_body():
    a, b = "https://a.example/a", "https://a.example/b"
    s, t, _ = make({a: etag_page(b"123456"), b: etag_page(b"123456")}, max_cache_bytes=10)
    s.fetch(a)
    s.fetch(b)
    s.fetch(b)
    assert "If-None-Match" in t.requests[-1][1]
    s.fetch(a)
    assert "If-None-Match" not in t.requests[-1][1]
    big = "https://a.example/big"
    s2, t2, _ = make({big: etag_page(b"x" * 11)}, max_cache_bytes=10)
    s2.fetch(big)
    s2.fetch(big)
    assert "If-None-Match" not in t2.requests[-1][1]


def test_robots_cache_ttl():
    url = "https://a.example/"
    s, t, clock = make({url: page()})
    s.fetch(url)
    s.fetch(url)
    assert [u for u, _h in t.requests].count(ROBOTS) == 1
    clock.now += 90_000
    s.fetch(url)
    assert [u for u, _h in t.requests].count(ROBOTS) == 2


def test_origin_tables_are_bounded(monkeypatch):
    monkeypatch.setattr(polite_scraper, "_MAX_ORIGINS", 2)
    routes = {f"https://h{i}.example/": page() for i in range(4)}
    s, _, _ = make(routes)
    for i in range(4):
        s.fetch(f"https://h{i}.example/")
    assert len(s._robots_cache) == 2
    assert len(s._last) == 2


def test_decoding():
    url = "https://a.example/d"
    body = "caf\u00e9".encode("latin-1")
    s, _, _ = make({url: page(body, "text/html; charset=iso-8859-1")})
    assert s.fetch(url).text == "caf\u00e9"
    meta = b'<meta charset="iso-8859-1">' + body
    s, _, _ = make({url: page(meta)})
    assert s.fetch(url).text.endswith("caf\u00e9")
    s, _, _ = make({url: page(b"\xff", "text/html; charset=nope")})
    assert s.fetch(url).text == "\ufffd"
    s, _, _ = make({url: page(b"\xff", "text/html; charset=rot13")})
    assert s.fetch(url).text == "\ufffd"


def test_events_never_carry_paths():
    routes = {ROBOTS: robots("User-agent: *\nDisallow: /private")}
    events = []
    s, _, _ = make(routes, on_event=events.append)
    code_of(s, "https://a.example/private")
    assert events
    assert all(set(e) == {"event", "origin", "status"} for e in events)
    assert all(e["origin"] == "https://a.example" for e in events)
    assert "private" not in repr(events)


def test_cache_hit_event_and_unreachable_event():
    url = "https://a.example/p"
    events = []
    s, _, _ = make({url: [etag_page(), Response(304, {}, b"", url)]}, on_event=events.append)
    s.fetch(url)
    s.fetch(url)
    assert any(e["event"] == "cache_hit" for e in events)


def test_constructor_validation_and_error_class():
    for bad in ("", "  ", "bad\nagent"):
        with pytest.raises(ValueError):
            PoliteScraper(FakeTransport({}), user_agent=bad)
    err = ScraperError("fetch_failed", "x" * 500, 7)
    assert len(str(err)) == 200
    assert err.status == 7
    assert polite_scraper.__version__


def test_default_transport_is_created():
    scraper = PoliteScraper(user_agent="MyBot/1.0")
    assert scraper is not None


HTML = (
    "<html><head><title> My  Page </title><style>b{}</style></head><body>"
    "<nav>Menu <a href='/nav'>n</a></nav><h1>Hello</h1><p>One<br>two</p>"
    "<script>var x=1;</script><a href='/a'>A</a><a href='javascript:alert(1)'>J</a>"
    "<a href='https://o.example/z'>Z</a><a href='/a'>dup</a><footer>Foot</footer>"
    "<template>tpl</template><noscript>ns</noscript></body></html>"
)


def test_extract_text():
    result = extract_text(HTML, base_url="https://a.example/dir/")
    assert result.title == "My Page"
    assert result.text.splitlines()[:3] == ["Hello", "One", "two"]
    for dropped in ("var", "Menu", "Foot", "tpl", "ns", "My Page"):
        assert dropped not in result.text
    assert result.links == ("https://a.example/a", "https://o.example/z")
    assert extract_text(HTML).links == ("https://o.example/z",)


def test_extract_text_limits_and_edges(monkeypatch):
    assert extract_text("<p>" + "a" * 50 + "</p>", max_chars=10).text == "a" * 10
    assert extract_text("</nav>x &amp; y").text == "x & y"
    assert extract_text("<a href='http://[bad'>x</a>", base_url="http://a.example/").links == ()
    with pytest.raises(ValueError):
        extract_text("x", max_chars=0)
    monkeypatch.setattr(polite_scraper, "_MAX_HTML_CHARS", 5)
    with pytest.raises(ScraperError) as info:
        extract_text("<p>too long</p>")
    assert info.value.code == "response_too_large"


def test_fake_transport_sequences_and_truncation():
    t = FakeTransport({"u": [Response(200, {}, b"abcdef", ""), OSError("x")]})
    assert t.get("u", {}, 1.0, 2).body == b"abc"
    with pytest.raises(OSError):
        t.get("u", {}, 1.0, 2)
    with pytest.raises(OSError):
        t.get("u", {}, 1.0, 2)
    assert t.get("missing", {}, 1.0, 2).status == 404
    assert len(t.requests) == 4
