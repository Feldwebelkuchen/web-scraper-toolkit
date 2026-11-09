"""Pagination strategies: "next" link or URL pattern."""

from __future__ import annotations

from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from .config import PaginationSpec


class Paginator:
    """Produce the sequence of list-page URLs for one start URL.

    Two strategies are supported:

    * ``next_selector``: the next page is found by following the ``href`` of
      the first node matching the selector on the current page.
    * ``url_pattern``: pages are generated from a pattern containing
      ``{page}``, starting at ``start_page``.

    ``max_pages`` always caps the number of pages.
    """

    def __init__(self, spec: PaginationSpec, start_url: str | None = None) -> None:
        if spec.url_pattern is None and start_url is None:
            raise ValueError("a start URL is required unless pagination.url_pattern is set")
        self.spec = spec
        self._start_url = start_url

    def first(self) -> str:
        """URL of the first page."""
        if self.spec.url_pattern is not None:
            return self.spec.url_pattern.format(page=self.spec.start_page)
        assert self._start_url is not None
        return self._start_url

    def next(self, current_url: str, tree: LexborHTMLParser, pages_done: int, items_on_page: int) -> str | None:
        """Return the URL of the following page, or ``None`` when finished.

        Args:
            current_url: URL of the page just processed (for relative links).
            tree: Parsed document of the current page.
            pages_done: Number of pages processed so far (including current).
            items_on_page: Items found on the current page; with
                ``stop_on_empty`` an empty page ends the crawl.
        """
        if pages_done >= self.spec.max_pages:
            return None
        if self.spec.stop_on_empty and items_on_page == 0:
            return None
        if self.spec.url_pattern is not None:
            return self.spec.url_pattern.format(page=self.spec.start_page + pages_done)
        if self.spec.next_selector:
            node = tree.css_first(self.spec.next_selector)
            href = node.attributes.get("href") if node is not None else None
            if not href:
                return None
            return urljoin(current_url, href)
        return None
