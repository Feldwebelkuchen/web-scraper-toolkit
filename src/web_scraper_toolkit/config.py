"""Job definitions: YAML loading, validation and typed configuration objects.

A job file describes *what* to scrape (start URLs, list selector, fields),
*how to navigate* (detail pages, pagination) and *how politely* to do it
(delays, retries, robots.txt). Everything is validated up front so that a
broken job fails fast with a readable error message instead of half-way
through a crawl.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_USER_AGENT = (
    "web-scraper-toolkit/0.1 "
    "(+https://github.com/Feldwebelkuchen/web-scraper-toolkit)"
)

VALID_TYPES = ("str", "int", "float")
_FIELD_KEYS = {
    "selector",
    "attr",
    "html",
    "regex",
    "type",
    "multiple",
    "separator",
    "default",
    "absolute",
}
_REQUEST_KEYS = {
    "timeout",
    "delay",
    "jitter",
    "retries",
    "backoff",
    "retry_wait",
    "user_agent",
    "headers",
}
_PAGINATION_KEYS = {"next_selector", "url_pattern", "start_page", "max_pages", "stop_on_empty"}
_JOB_KEYS = {
    "name",
    "start_urls",
    "list_selector",
    "fields",
    "detail",
    "pagination",
    "request",
    "respect_robots",
    "dedupe_key",
}


class ConfigError(ValueError):
    """Raised when a job definition is missing, unreadable or invalid."""


@dataclass(frozen=True)
class FieldSpec:
    """How to extract one column from a list item or a detail page.

    Attributes:
        name: Column name in the output.
        selector: CSS selector relative to the item node (``None`` = the item
            node itself).
        attr: Attribute to read instead of the text content (e.g. ``href``).
        html: Return the inner HTML instead of the text content.
        regex: Optional pattern applied to the raw value. The first capture
            group is used when present, otherwise the whole match.
        type: Output type: ``str`` (default), ``int`` or ``float``.
        multiple: Collect all matching nodes into a list instead of the first.
        separator: Used to join list values in flat exports (CSV/XLSX).
        default: Value used when nothing matches.
        absolute: Resolve the value as a URL relative to the page URL.
    """

    name: str
    selector: str | None = None
    attr: str | None = None
    html: bool = False
    regex: re.Pattern[str] | None = None
    type: str = "str"
    multiple: bool = False
    separator: str = " | "
    default: Any = None
    absolute: bool = False


@dataclass(frozen=True)
class DetailSpec:
    """Follow a URL stored in a list field and extract more fields from it."""

    follow: str
    fields: tuple[FieldSpec, ...]


@dataclass(frozen=True)
class PaginationSpec:
    """How to move from one list page to the next.

    Either ``next_selector`` (CSS selector of the "next" link) or
    ``url_pattern`` (a URL containing ``{page}``) is used. ``max_pages`` caps
    the number of list pages fetched *per start URL*.
    """

    next_selector: str | None = None
    url_pattern: str | None = None
    start_page: int = 1
    max_pages: int = 1
    stop_on_empty: bool = True


@dataclass(frozen=True)
class RequestSpec:
    """HTTP behaviour: timeouts, throttling, retries and identification."""

    timeout: float = 15.0
    delay: float = 1.0
    jitter: float = 0.5
    retries: int = 3
    backoff: float = 2.0
    retry_wait: float = 1.0
    user_agent: str = DEFAULT_USER_AGENT
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JobConfig:
    """A fully validated scraping job."""

    name: str
    start_urls: tuple[str, ...]
    list_selector: str
    fields: tuple[FieldSpec, ...]
    detail: DetailSpec | None = None
    pagination: PaginationSpec = field(default_factory=PaginationSpec)
    request: RequestSpec = field(default_factory=RequestSpec)
    respect_robots: bool = True
    dedupe_key: str | None = None

    @property
    def columns(self) -> list[str]:
        """Output columns in definition order (list fields, then detail fields)."""
        names = [f.name for f in self.fields]
        if self.detail:
            names.extend(f.name for f in self.detail.fields if f.name not in names)
        return names


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_job(path: str | Path) -> JobConfig:
    """Read a YAML job file and return a validated :class:`JobConfig`."""
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"job file not found: {file}")
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{file}: invalid YAML: {exc}") from exc
    return parse_job(data, source=str(file))


def parse_job(data: Any, *, source: str = "<job>") -> JobConfig:
    """Validate a parsed YAML mapping and build a :class:`JobConfig`.

    All problems are collected and reported together, so a user can fix a job
    file in one pass.
    """
    if not isinstance(data, dict):
        raise ConfigError(f"{source}: job must be a mapping at the top level")

    errors: list[str] = []
    _check_keys(data, _JOB_KEYS, "job", errors)

    name = data.get("name") or Path(source).stem
    if not isinstance(name, str) or not name.strip():
        errors.append("'name' must be a non-empty string")

    start_urls = _parse_start_urls(data.get("start_urls"), errors)

    list_selector = data.get("list_selector")
    if not isinstance(list_selector, str) or not list_selector.strip():
        errors.append("'list_selector' is required and must be a CSS selector string")

    fields = _parse_fields(data.get("fields"), "fields", errors)
    detail = _parse_detail(data.get("detail"), fields, errors)
    pagination = _parse_pagination(data.get("pagination"), errors)
    request = _parse_request(data.get("request"), errors)

    if not start_urls and not pagination.url_pattern:
        errors.append("either 'start_urls' or 'pagination.url_pattern' is required")

    respect_robots = data.get("respect_robots", True)
    if not isinstance(respect_robots, bool):
        errors.append("'respect_robots' must be true or false")

    dedupe_key = data.get("dedupe_key")
    if dedupe_key is not None:
        known = {f.name for f in fields} | ({f.name for f in detail.fields} if detail else set())
        if not isinstance(dedupe_key, str) or dedupe_key not in known:
            errors.append(f"'dedupe_key' must name a defined field, got {dedupe_key!r}")

    if errors:
        raise ConfigError(f"{source}: invalid job definition:\n  - " + "\n  - ".join(errors))

    return JobConfig(
        name=str(name).strip(),
        start_urls=start_urls,
        list_selector=str(list_selector).strip(),
        fields=fields,
        detail=detail,
        pagination=pagination,
        request=request,
        respect_robots=respect_robots,
        dedupe_key=dedupe_key,
    )


# --------------------------------------------------------------------------- #
# Section parsers
# --------------------------------------------------------------------------- #


def _check_keys(section: Mapping[str, Any], allowed: set[str], label: str, errors: list[str]) -> None:
    unknown = sorted(str(key) for key in section if key not in allowed)
    if unknown:
        errors.append(f"{label}: unknown option(s): {', '.join(unknown)}")


def _parse_start_urls(raw: Any, errors: list[str]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not all(isinstance(u, str) and u.strip() for u in raw):
        errors.append("'start_urls' must be a list of URL strings")
        return ()
    urls = tuple(u.strip() for u in raw)
    for url in urls:
        if not re.match(r"^https?://", url):
            errors.append(f"start URL must begin with http:// or https://: {url}")
    return urls


def _parse_fields(raw: Any, label: str, errors: list[str]) -> tuple[FieldSpec, ...]:
    if not isinstance(raw, dict) or not raw:
        errors.append(f"'{label}' must be a non-empty mapping of column name -> field spec")
        return ()
    specs: list[FieldSpec] = []
    for name, spec in raw.items():
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}: column names must be non-empty strings")
            continue
        if isinstance(spec, str):  # shorthand: name: "css selector"
            spec = {"selector": spec}
        if not isinstance(spec, dict):
            errors.append(f"{label}.{name}: must be a selector string or a mapping")
            continue
        _check_keys(spec, _FIELD_KEYS, f"{label}.{name}", errors)
        parsed = _parse_field(name.strip(), spec, f"{label}.{name}", errors)
        if parsed:
            specs.append(parsed)
    return tuple(specs)


def _parse_field(name: str, spec: Mapping[str, Any], label: str, errors: list[str]) -> FieldSpec | None:
    selector = spec.get("selector")
    if selector is not None and (not isinstance(selector, str) or not selector.strip()):
        errors.append(f"{label}: 'selector' must be a CSS selector string")
        return None

    regex = None
    if spec.get("regex") is not None:
        try:
            regex = re.compile(str(spec["regex"]), re.DOTALL)
        except re.error as exc:
            errors.append(f"{label}: invalid regex: {exc}")
            return None

    type_ = str(spec.get("type", "str"))
    if type_ not in VALID_TYPES:
        errors.append(f"{label}: 'type' must be one of {', '.join(VALID_TYPES)}")
        return None

    attr = spec.get("attr")
    html = bool(spec.get("html", False))
    if attr is not None and html:
        errors.append(f"{label}: 'attr' and 'html' are mutually exclusive")
        return None

    return FieldSpec(
        name=name,
        selector=selector.strip() if isinstance(selector, str) else None,
        attr=str(attr) if attr is not None else None,
        html=html,
        regex=regex,
        type=type_,
        multiple=bool(spec.get("multiple", False)),
        separator=str(spec.get("separator", " | ")),
        default=spec.get("default"),
        absolute=bool(spec.get("absolute", False)),
    )


def _parse_detail(raw: Any, list_fields: tuple[FieldSpec, ...], errors: list[str]) -> DetailSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        errors.append("'detail' must be a mapping with 'follow' and 'fields'")
        return None
    _check_keys(raw, {"follow", "fields"}, "detail", errors)
    follow = raw.get("follow")
    if not isinstance(follow, str) or follow not in {f.name for f in list_fields}:
        errors.append("'detail.follow' must name a list field that holds the detail URL")
    fields = _parse_fields(raw.get("fields"), "detail.fields", errors)
    if not isinstance(follow, str) or not fields:
        return None
    return DetailSpec(follow=follow, fields=fields)


def _parse_pagination(raw: Any, errors: list[str]) -> PaginationSpec:
    if raw is None:
        return PaginationSpec()
    if not isinstance(raw, dict):
        errors.append("'pagination' must be a mapping")
        return PaginationSpec()
    _check_keys(raw, _PAGINATION_KEYS, "pagination", errors)

    next_selector = raw.get("next_selector")
    url_pattern = raw.get("url_pattern")
    if next_selector is not None and url_pattern is not None:
        errors.append("pagination: use either 'next_selector' or 'url_pattern', not both")
    if url_pattern is not None and (not isinstance(url_pattern, str) or "{page}" not in url_pattern):
        errors.append("pagination.url_pattern must be a URL string containing '{page}'")

    max_pages = raw.get("max_pages", 1)
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        errors.append("pagination.max_pages must be a positive integer")
        max_pages = 1
    start_page = raw.get("start_page", 1)
    if not isinstance(start_page, int) or isinstance(start_page, bool):
        errors.append("pagination.start_page must be an integer")
        start_page = 1

    return PaginationSpec(
        next_selector=str(next_selector) if next_selector is not None else None,
        url_pattern=str(url_pattern) if isinstance(url_pattern, str) else None,
        start_page=start_page,
        max_pages=max_pages,
        stop_on_empty=bool(raw.get("stop_on_empty", True)),
    )


def _parse_request(raw: Any, errors: list[str]) -> RequestSpec:
    if raw is None:
        return RequestSpec()
    if not isinstance(raw, dict):
        errors.append("'request' must be a mapping")
        return RequestSpec()
    _check_keys(raw, _REQUEST_KEYS, "request", errors)

    def number(key: str, default: float, minimum: float = 0.0) -> float:
        value = raw.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
            errors.append(f"request.{key} must be a number >= {minimum:g}")
            return default
        return float(value)

    retries = raw.get("retries", 3)
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        errors.append("request.retries must be a non-negative integer")
        retries = 3

    headers = raw.get("headers", {})
    if not isinstance(headers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
    ):
        errors.append("request.headers must be a mapping of string -> string")
        headers = {}

    user_agent = raw.get("user_agent", DEFAULT_USER_AGENT)
    if not isinstance(user_agent, str) or not user_agent.strip():
        errors.append("request.user_agent must be a non-empty string")
        user_agent = DEFAULT_USER_AGENT

    return RequestSpec(
        timeout=number("timeout", 15.0, 0.1),
        delay=number("delay", 1.0),
        jitter=number("jitter", 0.5),
        retries=retries,
        backoff=number("backoff", 2.0, 1.0),
        retry_wait=number("retry_wait", 1.0),
        user_agent=user_agent.strip(),
        headers=dict(headers),
    )
