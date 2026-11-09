"""HTTP fetching with throttling, retries and a descriptive User-Agent.

The :class:`Fetcher` is the only place that talks to the network. It applies
a fixed delay plus random jitter between requests, retries transient failures
(HTTP 429, 5xx and network errors) with exponential backoff, honours
``Retry-After`` headers and raises :class:`FetchError` for everything else.

All time-related dependencies (sleep, random) are injectable, which keeps the
tests fast and deterministic.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable

import httpx

from .config import RequestSpec

log = logging.getLogger(__name__)

MAX_RETRY_WAIT = 60.0


class FetchError(RuntimeError):
    """A URL could not be fetched (after retries, if applicable)."""

    def __init__(self, url: str, reason: str, status: int | None = None) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Page:
    """A successfully fetched HTML document."""

    url: str
    final_url: str
    status: int
    text: str


class Fetcher:
    """Polite HTTP client: throttled, retrying, identifiable.

    Args:
        request: Timing and identification settings.
        transport: Optional ``httpx`` transport (use ``httpx.MockTransport``
            in tests).
        sleep: Function used to wait; defaults to :func:`time.sleep`.
        rng: Function returning a float in ``[0, 1)`` used for jitter.
    """

    def __init__(
        self,
        request: RequestSpec | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.request = request or RequestSpec()
        self._sleep = sleep
        self._rng = rng
        self._requests_made = 0
        self.retries = 0
        self.extra_delay = 0.0  # e.g. from robots.txt Crawl-delay
        headers = {
            "User-Agent": self.request.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en;q=0.9,*;q=0.5",
        }
        headers.update(self.request.headers)
        self._client = httpx.Client(
            headers=headers,
            timeout=self.request.timeout,
            follow_redirects=True,
            transport=transport,
        )

    # -- lifecycle -------------------------------------------------------- #

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- public API ------------------------------------------------------- #

    @property
    def requests_made(self) -> int:
        """Number of HTTP requests sent, including retries."""
        return self._requests_made

    def get(self, url: str) -> Page:
        """Fetch ``url`` politely; raise :class:`FetchError` on failure."""
        self._throttle()
        attempt = 0
        last_status: int | None = None
        while True:
            attempt += 1
            self._requests_made += 1
            retry_after: float | None = None
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                failure = f"network error ({exc.__class__.__name__})"
                last_status = None
            else:
                status = response.status_code
                if status < 400:
                    return Page(url=url, final_url=str(response.url), status=status, text=response.text)
                last_status = status
                if status == 429 or 500 <= status < 600:
                    failure = f"HTTP {status}"
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                else:
                    raise FetchError(url, f"HTTP {status}", status)

            if attempt > self.request.retries:
                raise FetchError(url, f"{failure} after {attempt} attempt(s)", last_status)

            wait = retry_after if retry_after is not None else self._backoff(attempt)
            wait = min(wait, MAX_RETRY_WAIT)
            self.retries += 1
            log.warning("%s: %s - retry %d/%d in %.1fs", url, failure, attempt, self.request.retries, wait)
            self._sleep(wait)

    # -- internals -------------------------------------------------------- #

    def _backoff(self, attempt: int) -> float:
        return self.request.retry_wait * (self.request.backoff ** (attempt - 1))

    def _throttle(self) -> None:
        """Wait ``delay + jitter`` before every request except the first."""
        if self._requests_made == 0:
            return
        delay = max(self.request.delay, self.extra_delay)
        wait = delay + self._rng() * self.request.jitter
        if wait > 0:
            self._sleep(wait)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header (seconds or HTTP date) into seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    delta = when.timestamp() - time.time()
    return max(0.0, delta)
