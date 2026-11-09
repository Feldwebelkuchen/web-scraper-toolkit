"""Command-line interface: ``scrape run | validate | sample``.

Exit codes:

* ``0`` success
* ``1`` finished, but some pages failed (partial result was still written)
* ``2`` invalid job file / arguments
* ``3`` no records were collected
* ``130`` interrupted by the user
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import ConfigError, JobConfig, load_job
from .export import FORMATS, export_records, infer_format
from .fetcher import Fetcher
from .scraper import Scraper
from .table import render_table

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_NO_DATA = 3
EXIT_INTERRUPTED = 130

log = logging.getLogger("web_scraper_toolkit")


def make_fetcher(job: JobConfig) -> Fetcher:
    """Create the HTTP client for a job (patched in tests)."""
    return Fetcher(job.request)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrape",
        description="Run YAML-defined scraping jobs against static websites.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("job", help="path to the YAML job file")
        verbosity = p.add_mutually_exclusive_group()
        verbosity.add_argument("-v", "--verbose", action="store_true", help="debug logging")
        verbosity.add_argument("-q", "--quiet", action="store_true", help="only warnings and errors")

    run = sub.add_parser("run", help="run a job and export the records")
    add_common(run)
    run.add_argument(
        "-o",
        "--out",
        action="append",
        help="output file (.csv, .json or .xlsx); repeat to export one crawl into several files. "
        "Default: <job name>.csv",
    )
    run.add_argument("-f", "--format", choices=FORMATS, help="override the format inferred from --out")
    run.add_argument("--max-pages", type=int, help="override pagination.max_pages")
    run.add_argument(
        "--ignore-robots",
        action="store_true",
        help="do NOT check robots.txt (only with permission of the site owner)",
    )

    validate = sub.add_parser("validate", help="check a job file and print its structure")
    add_common(validate)

    sample = sub.add_parser("sample", help="fetch a few pages and preview the records as a table")
    add_common(sample)
    sample.add_argument("--pages", type=int, default=1, help="list pages to fetch (default 1)")
    sample.add_argument("--limit", type=int, default=10, help="records to show (default 10)")
    sample.add_argument("--ignore-robots", action="store_true", help="do NOT check robots.txt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args)
    try:
        job = load_job(args.job)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        if args.command == "validate":
            return _cmd_validate(job, args)
        if args.command == "run":
            return _cmd_run(job, args)
        return _cmd_sample(job, args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def _cmd_validate(job: JobConfig, args: argparse.Namespace) -> int:
    pag = job.pagination
    if pag.url_pattern:
        pagination = f"url pattern {pag.url_pattern!r}, pages {pag.start_page}..{pag.start_page + pag.max_pages - 1}"
    elif pag.next_selector:
        pagination = f"follow {pag.next_selector!r}, max {pag.max_pages} page(s) per start URL"
    else:
        pagination = "none (first page only)"
    lines = [
        f"OK: {args.job}",
        f"  name:          {job.name}",
        f"  start URLs:    {len(job.start_urls)}",
        f"  list selector: {job.list_selector}",
        f"  fields:        {', '.join(f.name for f in job.fields)}",
        f"  detail fields: {', '.join(f.name for f in job.detail.fields) if job.detail else '-'}",
        f"  pagination:    {pagination}",
        f"  dedupe key:    {job.dedupe_key or '-'}",
        f"  robots.txt:    {'respected' if job.respect_robots else 'IGNORED'}",
        f"  politeness:    delay {job.request.delay:g}s + jitter {job.request.jitter:g}s, "
        f"{job.request.retries} retries, timeout {job.request.timeout:g}s",
    ]
    print("\n".join(lines))
    return EXIT_OK


def _cmd_run(job: JobConfig, args: argparse.Namespace) -> int:
    outputs: list[tuple[Path, str]] = []
    try:
        for raw in args.out or [f"{job.name}.csv"]:
            path = Path(raw)
            outputs.append((path, args.format or infer_format(path)))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if args.max_pages is not None and args.max_pages < 1:
        print("error: --max-pages must be >= 1", file=sys.stderr)
        return EXIT_CONFIG

    scraper = Scraper(
        job,
        fetcher=make_fetcher(job),
        max_pages=args.max_pages,
        respect_robots=False if args.ignore_robots else None,
    )
    result = scraper.run()
    if not result.records:
        print(f"no records collected - {result.stats.summary()}", file=sys.stderr)
        return EXIT_NO_DATA
    for path, fmt in outputs:
        export_records(result.records, path, result.columns, fmt)
        print(f"wrote {len(result.records)} records to {path} ({fmt})", file=sys.stderr)
    print(f"summary: {result.stats.summary()}", file=sys.stderr)
    return EXIT_PARTIAL if result.stats.errors else EXIT_OK


def _cmd_sample(job: JobConfig, args: argparse.Namespace) -> int:
    if args.pages < 1 or args.limit < 1:
        print("error: --pages and --limit must be >= 1", file=sys.stderr)
        return EXIT_CONFIG
    scraper = Scraper(
        job,
        fetcher=make_fetcher(job),
        max_pages=args.pages,
        respect_robots=False if args.ignore_robots else None,
        limit=args.limit,
    )
    result = scraper.run()
    print(render_table(result.records[: args.limit], result.columns))
    print(f"\nsummary: {result.stats.summary()}", file=sys.stderr)
    if not result.records:
        return EXIT_NO_DATA
    return EXIT_PARTIAL if result.stats.errors else EXIT_OK


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.INFO
    if getattr(args, "verbose", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
