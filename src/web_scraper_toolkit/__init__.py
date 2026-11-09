"""web-scraper-toolkit: a configurable, polite scraper for static websites.

Define a scraping job in YAML (start URLs, list selector, field selectors,
detail pages, pagination), run it from the command line and get clean
CSV/JSON/XLSX output. The toolkit respects robots.txt by default, throttles
requests and retries transient failures with exponential backoff.
"""

from .config import ConfigError, JobConfig, load_job, parse_job
from .export import export_records
from .fetcher import FetchError, Fetcher, Page
from .scraper import Scraper, ScrapeResult, ScrapeStats

__version__ = "0.1.0"

__all__ = [
    "ConfigError",
    "FetchError",
    "Fetcher",
    "JobConfig",
    "Page",
    "ScrapeResult",
    "ScrapeStats",
    "Scraper",
    "__version__",
    "export_records",
    "load_job",
    "parse_job",
]
