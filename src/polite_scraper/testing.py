"""Deterministic test doubles for polite_scraper."""

from __future__ import annotations

from collections.abc import Mapping

from polite_scraper import Response

__all__ = ["FakeClock", "FakeTransport"]

Route = Response | Exception | list[Response | Exception]


class FakeClock:
    """A clock whose ``sleep`` records the request and advances time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        """Record a sleep and advance the clock."""
        self.sleeps.append(seconds)
        self.now += seconds


class FakeTransport:
    """A transport serving canned routes keyed by URL and recording every request."""

    def __init__(self, routes: Mapping[str, Route]) -> None:
        self._routes = dict(routes)
        self._counts: dict[str, int] = {}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, headers: Mapping[str, str], timeout: float, max_bytes: int) -> Response:
        """Return the route for ``url`` (404 when missing), truncating to max_bytes + 1."""
        self.requests.append((url, dict(headers)))
        route = self._routes.get(url)
        item: Response | Exception | None
        if isinstance(route, list):
            index = self._counts.get(url, 0)
            self._counts[url] = index + 1
            item = route[min(index, len(route) - 1)]
        else:
            item = route
        if item is None:
            return Response(404, {}, b"", url)
        if isinstance(item, Exception):
            raise item
        return Response(item.status, item.headers, item.body[: max_bytes + 1], url)
