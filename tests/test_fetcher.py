import httpx
import pytest

from web_scraper_toolkit.config import RequestSpec
from web_scraper_toolkit.fetcher import FetchError, Fetcher, _parse_retry_after


class Flaky:
    """Mock handler that fails ``failures`` times before succeeding."""

    def __init__(self, failures: int, status: int = 503, headers: dict | None = None, exc: type | None = None):
        self.failures = failures
        self.status = status
        self.headers = headers or {}
        self.exc = exc
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.failures:
            if self.exc is not None:
                raise self.exc("boom", request=request)
            return httpx.Response(self.status, text="busy", headers=self.headers)
        return httpx.Response(200, text="<html>ok</html>")


def make(handler, **overrides):
    sleeps: list[float] = []
    spec = RequestSpec(**{"delay": 0.0, "jitter": 0.0, "retry_wait": 1.0, "backoff": 2.0, "retries": 3, **overrides})
    fetcher = Fetcher(spec, transport=httpx.MockTransport(handler), sleep=sleeps.append, rng=lambda: 0.5)
    return fetcher, sleeps


def test_retries_5xx_with_exponential_backoff():
    handler = Flaky(failures=2)
    fetcher, sleeps = make(handler)
    page = fetcher.get("https://x.test/a")
    assert page.status == 200 and page.text == "<html>ok</html>"
    assert handler.calls == 3
    assert fetcher.retries == 2
    assert sleeps == [1.0, 2.0]  # retry_wait * backoff**(attempt-1)


def test_gives_up_after_configured_retries():
    handler = Flaky(failures=10, status=500)
    fetcher, _ = make(handler, retries=2)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://x.test/a")
    assert handler.calls == 3
    assert info.value.status == 500
    assert "HTTP 500 after 3 attempt(s)" in str(info.value)


def test_429_honours_retry_after_header():
    handler = Flaky(failures=1, status=429, headers={"Retry-After": "7"})
    fetcher, sleeps = make(handler)
    fetcher.get("https://x.test/a")
    assert sleeps == [7.0]


def test_network_errors_are_retried():
    handler = Flaky(failures=1, exc=httpx.ConnectError)
    fetcher, sleeps = make(handler)
    fetcher.get("https://x.test/a")
    assert handler.calls == 2 and len(sleeps) == 1


def test_404_is_not_retried():
    handler = Flaky(failures=5, status=404)
    fetcher, sleeps = make(handler)
    with pytest.raises(FetchError) as info:
        fetcher.get("https://x.test/a")
    assert handler.calls == 1 and sleeps == [] and info.value.status == 404


def test_rate_limit_sleeps_between_requests_only():
    handler = Flaky(failures=0)
    fetcher, sleeps = make(handler, delay=1.0, jitter=0.5)  # rng is fixed at 0.5 -> jitter 0.25
    fetcher.get("https://x.test/a")
    assert sleeps == []
    fetcher.get("https://x.test/b")
    fetcher.get("https://x.test/c")
    assert sleeps == [1.25, 1.25]


def test_extra_delay_from_robots_overrides_smaller_delay():
    handler = Flaky(failures=0)
    fetcher, sleeps = make(handler, delay=1.0)
    fetcher.extra_delay = 3.0
    fetcher.get("https://x.test/a")
    fetcher.get("https://x.test/b")
    assert sleeps == [3.0]


def test_user_agent_header_is_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text="")

    fetcher, _ = make(handler, user_agent="my-bot/1.0 (contact: me@example.com)")
    fetcher.get("https://x.test/")
    assert seen["ua"] == "my-bot/1.0 (contact: me@example.com)"


def test_parse_retry_after_variants():
    assert _parse_retry_after("12") == 12.0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("garbage") is None
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # in the past -> no wait
