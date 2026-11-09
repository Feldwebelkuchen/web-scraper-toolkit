"""Shared fixtures: an in-memory website served through ``httpx.MockTransport``.

No test touches the network. ``site`` is a dict ``URL -> body`` (or
``URL -> (status, body)``); ``make_transport`` turns it into a transport and
records every request so tests can assert on them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import httpx
import pytest

from web_scraper_toolkit.config import RequestSpec
from web_scraper_toolkit.fetcher import Fetcher

BASE = "https://example.test"


def list_page(page: int, items: list[tuple[str, str, str]], next_page: int | None) -> str:
    """Build a list page with ``items`` = (slug, title, price)."""
    cards = "\n".join(
        f'<article class="card"><h3><a href="/items/{slug}.html" title="{title}">{title[:8]}...</a></h3>'
        f'<p class="price">£{price}</p><p class="stock">  In stock  </p>'
        f'<p class="rating Three"></p><span class="tag">t{page}</span><span class="tag">x</span></article>'
        for slug, title, price in items
    )
    nav = f'<li class="next"><a href="page-{next_page}.html">next</a></li>' if next_page else ""
    return f"<html><body><h1>Page {page}</h1>{cards}<ul class='pager'>{nav}</ul></body></html>"


def detail_page(title: str, upc: str, category: str) -> str:
    return (
        "<html><body><ul class='breadcrumb'><li><a href='/'>Home</a></li><li><a href='/b'>Books</a></li>"
        f"<li><a href='/c'>{category}</a></li><li class='active'>{title}</li></ul>"
        f"<h1>{title}</h1><table class='info'><tr><th>UPC</th><td>{upc}</td></tr></table>"
        "<div id='desc'></div><p>Some description text</p></body></html>"
    )


def build_site() -> dict[str, str | tuple[int, str]]:
    """Two list pages (3 + 2 items, one duplicate) plus detail pages and robots.txt."""
    page1 = [("alpha", "Alpha Book", "10.00"), ("beta", "Beta Book", "20.50"), ("gamma", "Gamma Book", "30.00")]
    page2 = [("delta", "Delta Book", "40.00"), ("alpha", "Alpha Book", "10.00")]
    site: dict[str, str | tuple[int, str]] = {
        f"{BASE}/robots.txt": "User-agent: *\nDisallow: /private/\nDisallow: /items/gamma.html\n",
        f"{BASE}/catalogue/page-1.html": list_page(1, page1, 2),
        f"{BASE}/catalogue/page-2.html": list_page(2, page2, None),
        f"{BASE}/items/alpha.html": detail_page("Alpha Book", "UPC-A", "Poetry"),
        f"{BASE}/items/beta.html": detail_page("Beta Book", "UPC-B", "Travel"),
        f"{BASE}/items/gamma.html": detail_page("Gamma Book", "UPC-G", "Secret"),
        f"{BASE}/items/delta.html": detail_page("Delta Book", "UPC-D", "Poetry"),
        f"{BASE}/private/page.html": list_page(9, [], None),
        f"{BASE}/missing.html": (404, "not found"),
    }
    return site


@dataclass
class Recorder:
    """Tracks requests made against a mock site."""

    requests: list[str] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def make_transport(site: dict[str, str | tuple[int, str]], recorder: Recorder | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if recorder is not None:
            recorder.requests.append(url)
        entry = site.get(url)
        if entry is None:
            return httpx.Response(404, text="not found")
        if isinstance(entry, tuple):
            status, body = entry
            return httpx.Response(status, text=body)
        return httpx.Response(200, text=entry, headers={"content-type": "text/html; charset=utf-8"})

    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _reset_logging():
    """Undo ``logging.basicConfig`` calls made by the CLI during a test."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def site() -> dict[str, str | tuple[int, str]]:
    return build_site()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def fetcher_factory(recorder: Recorder) -> Callable[..., Fetcher]:
    """Return ``make(site, **request_overrides)`` producing an offline Fetcher."""

    def make(site: dict[str, str | tuple[int, str]], **overrides: object) -> Fetcher:
        spec = RequestSpec(**{"delay": 0.0, "jitter": 0.0, "retry_wait": 0.0, **overrides})  # type: ignore[arg-type]
        return Fetcher(spec, transport=make_transport(site, recorder), sleep=recorder.sleep, rng=lambda: 0.5)

    return make


@pytest.fixture
def job_dict() -> dict:
    """A complete, valid job definition against the mock site."""
    return {
        "name": "test-job",
        "start_urls": [f"{BASE}/catalogue/page-1.html"],
        "list_selector": "article.card",
        "fields": {
            "title": {"selector": "h3 a", "attr": "title"},
            "price": {"selector": ".price", "regex": r"([0-9.]+)", "type": "float"},
            "stock": ".stock",
            "rating": {"selector": ".rating", "attr": "class", "regex": r"rating (\w+)"},
            "tags": {"selector": ".tag", "multiple": True},
            "url": {"selector": "h3 a", "attr": "href", "absolute": True},
        },
        "detail": {
            "follow": "url",
            "fields": {
                "category": "ul.breadcrumb li:nth-child(3) a",
                "upc": "table.info tr:nth-child(1) td",
            },
        },
        "pagination": {"next_selector": "li.next a", "max_pages": 5},
        "dedupe_key": "url",
        "request": {"delay": 0, "jitter": 0, "retry_wait": 0},
    }
