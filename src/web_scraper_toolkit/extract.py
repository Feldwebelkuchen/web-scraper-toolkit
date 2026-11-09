"""HTML parsing and field extraction (selectolax / lexbor backend).

The extraction pipeline for one field is::

    select nodes -> raw value (text | attribute | html) -> regex -> URL
    resolution -> type conversion -> default

Every step is tolerant: a missing node or a non-matching regex yields the
field's ``default`` (``None`` unless configured) instead of raising.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .config import FieldSpec

log = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_html(text: str) -> LexborHTMLParser:
    """Parse an HTML document."""
    return LexborHTMLParser(text)


def select_items(tree: LexborHTMLParser | LexborNode, selector: str) -> list[LexborNode]:
    """Return all nodes matching ``selector``."""
    return list(tree.css(selector))


def extract_record(node: LexborNode, fields: Sequence[FieldSpec], base_url: str) -> dict[str, Any]:
    """Extract all ``fields`` from one item node into a flat dict."""
    return {spec.name: extract_field(node, spec, base_url) for spec in fields}


def extract_field(node: LexborNode, spec: FieldSpec, base_url: str) -> Any:
    """Extract a single field from ``node`` according to ``spec``."""
    targets: list[LexborNode] = list(node.css(spec.selector)) if spec.selector else [node]
    if not spec.multiple:
        targets = targets[:1]

    values: list[Any] = []
    for target in targets:
        raw = _raw_value(target, spec)
        if raw is None:
            continue
        value = _postprocess(raw, spec, base_url)
        if value is not None:
            values.append(value)

    if spec.multiple:
        if values:
            return values
        return spec.default if spec.default is not None else []
    return values[0] if values else spec.default


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _raw_value(target: LexborNode, spec: FieldSpec) -> str | None:
    if spec.attr is not None:
        value = target.attributes.get(spec.attr)
        return value if value is not None else None
    if spec.html:
        return target.html
    return normalize_whitespace(target.text(separator=" ", strip=True))


def _postprocess(raw: str, spec: FieldSpec, base_url: str) -> Any:
    value: str = raw.strip()
    if spec.regex is not None:
        match = spec.regex.search(value)
        if not match:
            return None
        value = (match.group(1) if match.groups() else match.group(0)) or ""
        value = value.strip()
    if spec.absolute and value:
        value = urljoin(base_url, value)
    return convert(value, spec.type)


def convert(value: str, type_: str) -> Any:
    """Convert a string to ``str``/``int``/``float``.

    Numeric conversion is forgiving: when the whole string is not a number,
    the first number-like token is used and a decimal comma is accepted
    (``"£51.77"`` -> ``51.77``, ``"1,5 kg"`` -> ``1.5``). Returns ``None`` when
    no number is present.
    """
    if type_ == "str":
        return value
    if value == "":
        return None
    try:
        return int(value) if type_ == "int" else float(value)
    except ValueError:
        pass
    match = _NUMBER.search(value)
    if not match:
        return None
    token = match.group(0).replace(",", ".")
    try:
        number = float(token)
    except ValueError:
        return None
    return int(number) if type_ == "int" else number


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace (including newlines) into single spaces."""
    return _WHITESPACE.sub(" ", text).strip()
