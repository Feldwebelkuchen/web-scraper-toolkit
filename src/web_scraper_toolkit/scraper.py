"""The crawl loop: list pages -> items -> optional detail pages -> records."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterator

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .config import JobConfig
from .extract import extract_record, parse_html, select_items
from .fetcher import FetchError, Fetcher
from .pagination import Paginator
from .robots import RobotsPolicy

log = logging.getLogger(__name__)


@dataclass
class ScrapeStats:
    """Counters collected during a run."""

    list_pages: int = 0
    detail_pages: int = 0
    records: int = 0
    duplicates: int = 0
    blocked_by_robots: int = 0
    retries: int = 0
    requests: int = 0
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def summary(self) -> str:
        """One-line, human-readable summary."""
        return (
            f"{self.records} records, {self.list_pages} list pages, {self.detail_pages} detail pages, "
            f"{self.requests} requests ({self.retries} retries), {self.duplicates} duplicates skipped, "
            f"{self.blocked_by_robots} blocked by robots.txt, {self.error_count} errors, "
            f"{self.duration:.1f} s"
        )


@dataclass
class ScrapeResult:
    """Records plus the statistics of the run that produced them."""

    records: list[dict[str, Any]]
    columns: list[str]
    stats: ScrapeStats


class Scraper:
    """Run one :class:`JobConfig` to completion.

    Args:
        job: Validated job definition.
        fetcher: HTTP client to use (created from ``job.request`` by default).
        max_pages: Override ``pagination.max_pages`` (e.g. for previews).
        respect_robots: Override the job's robots.txt setting.
        limit: Stop after this many records (preview mode).
    """

    def __init__(
        self,
        job: JobConfig,
        *,
        fetcher: Fetcher | None = None,
        max_pages: int | None = None,
        respect_robots: bool | None = None,
        limit: int | None = None,
    ) -> None:
        self.job = job
        self.fetcher = fetcher or Fetcher(job.request)
        self._owns_fetcher = fetcher is None
        self.pagination = (
            replace(job.pagination, max_pages=max_pages) if max_pages is not None else job.pagination
        )
        self.limit = limit
        robots_enabled = job.respect_robots if respect_robots is None else respect_robots
        self.robots = RobotsPolicy(self.fetcher.get, job.request.user_agent, enabled=robots_enabled)
        self.stats = ScrapeStats()
        self._seen_keys: set[Any] = set()
        self._dedupe_in_list = job.dedupe_key in {f.name for f in job.fields}

    # -- public ----------------------------------------------------------- #

    def run(self) -> ScrapeResult:
        """Crawl all start URLs and return the collected records."""
        started = time.monotonic()
        records: list[dict[str, Any]] = []
        if not self.robots.enabled:
            log.warning("robots.txt checks are DISABLED for this run")
        try:
            for start_url in self._start_urls():
                self._apply_crawl_delay(start_url)
                for record in self._crawl_from(start_url):
                    records.append(record)
                    if self.limit is not None and len(records) >= self.limit:
                        break
                if self.limit is not None and len(records) >= self.limit:
                    log.info("record limit of %d reached", self.limit)
                    break
        finally:
            self.stats.records = len(records)
            self.stats.retries = self.fetcher.retries
            self.stats.requests = self.fetcher.requests_made
            self.stats.duration = time.monotonic() - started
            if self._owns_fetcher:
                self.fetcher.close()
        log.info("done: %s", self.stats.summary())
        return ScrapeResult(records=records, columns=self.job.columns, stats=self.stats)

    # -- crawl ------------------------------------------------------------ #

    def _start_urls(self) -> list[str | None]:
        if self.pagination.url_pattern is not None:
            return [None]
        return list(self.job.start_urls)

    def _crawl_from(self, start_url: str | None) -> Iterator[dict[str, Any]]:
        paginator = Paginator(self.pagination, start_url)
        url: str | None = paginator.first()
        pages_done = 0
        while url is not None:
            tree, items = self._fetch_list_page(url, pages_done + 1)
            pages_done += 1
            if tree is None:
                return
            for node in items:
                record = extract_record(node, self.job.fields, url)
                if self._dedupe_in_list and self._is_duplicate(record):
                    continue
                if self.job.detail:
                    self._enrich_with_detail(record)
                    if not self._dedupe_in_list and self._is_duplicate(record):
                        continue
                yield record
            url = paginator.next(url, tree, pages_done, len(items))

    def _fetch_list_page(self, url: str, page_no: int) -> tuple[LexborHTMLParser | None, list[LexborNode]]:
        if not self.robots.allowed(url):
            self.stats.blocked_by_robots += 1
            self._error(url, "disallowed by robots.txt")
            return None, []
        try:
            page = self.fetcher.get(url)
        except FetchError as exc:
            self._error(url, exc.reason)
            return None, []
        self.stats.list_pages += 1
        tree = parse_html(page.text)
        items = select_items(tree, self.job.list_selector)
        log.info("list page %d/%d %s -> %d items", page_no, self.pagination.max_pages, url, len(items))
        if not items:
            log.warning("%s: no items matched %r", url, self.job.list_selector)
        return tree, items

    def _enrich_with_detail(self, record: dict[str, Any]) -> None:
        assert self.job.detail is not None
        detail = self.job.detail
        for spec in detail.fields:
            record.setdefault(spec.name, spec.default)
        detail_url = record.get(detail.follow)
        if not isinstance(detail_url, str) or not detail_url:
            self._error("<item>", f"detail field {detail.follow!r} is empty - detail page skipped")
            return
        if not self.robots.allowed(detail_url):
            self.stats.blocked_by_robots += 1
            self._error(detail_url, "disallowed by robots.txt")
            return
        try:
            page = self.fetcher.get(detail_url)
        except FetchError as exc:
            self._error(detail_url, exc.reason)
            return
        self.stats.detail_pages += 1
        log.debug("detail page %s", detail_url)
        tree = parse_html(page.text)
        record.update(extract_record(tree.root, detail.fields, page.final_url))

    def _is_duplicate(self, record: dict[str, Any]) -> bool:
        key_name = self.job.dedupe_key
        if key_name is None:
            return False
        key = record.get(key_name)
        if key is None:
            return False
        if isinstance(key, list):
            key = tuple(key)
        if key in self._seen_keys:
            self.stats.duplicates += 1
            log.debug("duplicate %s=%r skipped", key_name, key)
            return True
        self._seen_keys.add(key)
        return False

    def _apply_crawl_delay(self, start_url: str | None) -> None:
        if start_url is None:
            return
        delay = self.robots.crawl_delay(start_url)
        if delay is not None and delay > self.job.request.delay:
            log.info("robots.txt asks for a crawl delay of %.1fs - slowing down", delay)
            self.fetcher.extra_delay = delay

    def _error(self, url: str, reason: str) -> None:
        self.stats.errors.append(f"{url}: {reason}")
        log.error("%s: %s", url, reason)
