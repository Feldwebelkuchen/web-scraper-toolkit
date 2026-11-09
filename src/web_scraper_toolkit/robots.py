"""robots.txt handling.

Every host is asked once for ``/robots.txt``; the answer is cached for the
lifetime of the scraper. Rules are interpreted with the standard library's
:mod:`urllib.robotparser`. The policy is deliberately conservative:

* ``2xx``: rules apply.
* ``4xx`` (no robots.txt): everything is allowed, as the standard suggests.
* ``5xx`` / network failure: everything is *disallowed* until the file can be
  read - we would rather miss a crawl than ignore a site's wishes.

A ``Crawl-delay`` directive for our user agent is exposed via
:meth:`RobotsPolicy.crawl_delay` so the scraper can slow down accordingly.
"""

from __future__ import annotations

import logging
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .fetcher import FetchError, Page

log = logging.getLogger(__name__)

_ALLOW_ALL = "allow-all"
_DISALLOW_ALL = "disallow-all"


class RobotsPolicy:
    """Decide whether a URL may be fetched according to robots.txt.

    Args:
        fetch: Callable returning a :class:`Page` for a URL (normally
            ``Fetcher.get``).
        user_agent: Full User-Agent string; the product token before ``/`` is
            matched against robots.txt groups.
        enabled: When ``False`` every URL is allowed (explicit opt-out).
    """

    def __init__(self, fetch: Callable[[str], Page], user_agent: str, *, enabled: bool = True) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        self.enabled = enabled
        self._cache: dict[str, RobotFileParser | str] = {}

    def allowed(self, url: str) -> bool:
        """Return ``True`` if ``url`` may be fetched."""
        if not self.enabled:
            return True
        rules = self._rules_for(url)
        if rules == _ALLOW_ALL:
            return True
        if rules == _DISALLOW_ALL:
            return False
        assert isinstance(rules, RobotFileParser)
        return rules.can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        """Return the ``Crawl-delay`` (seconds) for our agent, if declared."""
        if not self.enabled:
            return None
        rules = self._rules_for(url)
        if not isinstance(rules, RobotFileParser):
            return None
        delay = rules.crawl_delay(self._user_agent)
        try:
            return float(delay) if delay is not None else None
        except (TypeError, ValueError):
            return None

    # -- internals -------------------------------------------------------- #

    def _rules_for(self, url: str) -> RobotFileParser | str:
        parts = urlsplit(url)
        base = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        if base not in self._cache:
            self._cache[base] = self._load(base)
        return self._cache[base]

    def _load(self, base: str) -> RobotFileParser | str:
        robots_url = f"{base}/robots.txt"
        try:
            page = self._fetch(robots_url)
        except FetchError as exc:
            if exc.status is not None and 400 <= exc.status < 500:
                log.info("%s: not found (HTTP %s) - no restrictions", robots_url, exc.status)
                return _ALLOW_ALL
            log.warning("%s: unreachable (%s) - treating the whole host as disallowed", robots_url, exc.reason)
            return _DISALLOW_ALL
        parser = RobotFileParser()
        parser.parse(page.text.splitlines())
        log.info("%s: loaded", robots_url)
        return parser
