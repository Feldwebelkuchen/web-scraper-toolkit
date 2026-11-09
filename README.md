# web-scraper-toolkit

Turn any static website into a clean spreadsheet with a 30-line YAML file - politely, repeatably, without writing code.

```
$ scrape run examples/books.yaml --out books.xlsx
21:32:35 INFO    list page 1/3 https://books.toscrape.com/catalogue/page-1.html -> 20 items
...
wrote 60 records to books.xlsx (xlsx)
summary: 60 records, 3 list pages, 60 detail pages, 64 requests (0 retries), 0 duplicates skipped, 0 blocked by robots.txt, 0 errors, 98.1 s
```

## What you get

- A command-line tool (`scrape`) that runs **declarative scraping jobs** defined in YAML: start URLs, a list selector, field selectors, optional detail pages, pagination.
- **Clean output** as CSV, JSON or formatted XLSX (bold header, frozen header row, autofilter, sized columns) - ready to hand to a client.
- **Responsible defaults**: robots.txt is respected, requests are throttled with jitter, failures are retried with backoff, and the crawler identifies itself with a contact address.
- A **tested, typed Python package** (59 offline tests) you can extend: every job is a `JobConfig`, every run returns records plus statistics.

## Features

| Area | Details |
|---|---|
| Job definition | YAML: `start_urls`, `list_selector`, `fields` (CSS selector + `attr`/`html`/text, `regex` post-processing, `type` str/int/float, `multiple`, `default`, `absolute` URLs) |
| Detail pages | `detail.follow` names the list field that holds the URL; detail fields are merged into the record |
| Pagination | "next" link selector **or** URL pattern with `{page}`; `max_pages` cap; stops on empty pages |
| Politeness | fixed delay + random jitter, `Crawl-delay` from robots.txt honoured, descriptive User-Agent with project URL, timeout |
| Robustness | retries with exponential backoff on 429 / 5xx / network errors, `Retry-After` honoured, non-retryable errors recorded per URL, run continues |
| robots.txt | checked per host and cached; **on by default**, can only be switched off explicitly (`respect_robots: false` or `--ignore-robots`) |
| Data quality | whitespace normalisation, forgiving numeric conversion (`"£51.77"` -> `51.77`), de-duplication by a key field |
| Output | CSV (UTF-8), JSON (lists preserved), XLSX (openpyxl, formatted) - several files from one crawl via repeated `--out` |
| Observability | progress log per page, final summary (pages, records, requests, retries, errors, duration), meaningful exit codes |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

scrape validate examples/books.yaml          # check the job file
scrape sample   examples/books.yaml --pages 1 --limit 5   # preview as a table
scrape run      examples/books.yaml --out books.xlsx --out books.csv
```

Requires Python 3.10+. Dependencies: `httpx`, `selectolax`, `pyyaml`, `openpyxl`.

## A job file, explained

`examples/books.yaml` scrapes the official scraping sandbox [books.toscrape.com](https://books.toscrape.com):

```yaml
name: books-toscrape
start_urls:
  - https://books.toscrape.com/catalogue/page-1.html

request:                       # politeness & identification
  user_agent: "web-scraper-toolkit/0.1 (+https://github.com/Feldwebelkuchen/web-scraper-toolkit)"
  delay: 1.0                   # seconds between requests ...
  jitter: 0.5                  # ... plus up to 0.5 s random
  retries: 3                   # 429 / 5xx / network errors, backoff 1 s, 2 s, 4 s
respect_robots: true           # default

list_selector: "article.product_pod"     # one node per record

fields:
  title:        { selector: "h3 a", attr: title }
  price:        { selector: ".price_color", regex: "([0-9.]+)", type: float }
  availability: { selector: ".availability" }                      # text, whitespace-normalised
  rating:       { selector: ".star-rating", attr: class, regex: "star-rating (\\w+)" }
  url:          { selector: "h3 a", attr: href, absolute: true }   # resolved against the page URL

detail:                        # follow each record's `url` and add more columns
  follow: url
  fields:
    category:    { selector: "ul.breadcrumb li:nth-child(3) a" }
    upc:         { selector: "table.table-striped tr:nth-child(1) td" }
    stock_count: { selector: ".product_main .availability", regex: "\\((\\d+) available\\)", type: int }

pagination:
  next_selector: "li.next a"   # follow the "next" link ...
  max_pages: 3                 # ... at most 3 list pages per start URL

dedupe_key: upc                # drop records whose UPC was already seen
```

Reading it top to bottom: fetch the start URL, select every `article.product_pod`, extract the five list fields from each, open the book's detail page and add three more columns, follow the "next" link up to three times, drop duplicates by UPC, export.

A second example, `examples/quotes.yaml`, shows multi-value fields (`tags`, `multiple: true`) and pagination without detail pages.

## Example output

Produced by the run shown at the top (`examples/output/books-sample.xlsx` and `.csv`, first 5 of 60 rows; the `url` and `description` columns are omitted here for width):

| title | price | availability | rating | category | upc | stock_count |
|---|---:|---|---|---|---|---:|
| A Light in the Attic | 51.77 | In stock | Three | Poetry | a897fe39b1053632 | 22 |
| Tipping the Velvet | 53.74 | In stock | One | Historical Fiction | 90fa61229261140a | 20 |
| Soumission | 50.10 | In stock | One | Fiction | 6957f44c3847a760 | 20 |
| Sharp Objects | 47.82 | In stock | Four | Mystery | e00eb4fd7b871a48 | 20 |
| Sapiens: A Brief History of Humankind | 54.23 | In stock | Five | History | 4165285e1663650f | 20 |

Run metrics: **60 records, 3 list pages + 60 detail pages, 64 requests, 0 retries, 0 errors, 98.1 s** at a polite 1-1.5 s per request. (The sandbox's own `description` paragraphs contain a truncated preview followed by the full text; the scraper reproduces the page faithfully.)

## Command-line reference

```
scrape run      JOB [--out FILE ...] [--format csv|json|xlsx] [--max-pages N] [--ignore-robots] [-v|-q]
scrape sample   JOB [--pages N] [--limit N] [--ignore-robots]      # preview records as a text table
scrape validate JOB                                                # check the job file, print its structure
```

Exit codes: `0` success - `1` finished with some failed pages (partial output written) - `2` invalid job file or arguments - `3` no records collected - `130` interrupted.

## Configuration reference

| Key | Type / default | Meaning |
|---|---|---|
| `name` | string (file name) | Job name; default output file is `<name>.csv` |
| `start_urls` | list of URLs | Entry pages (not needed with `pagination.url_pattern`) |
| `list_selector` | CSS selector | One match = one record |
| `fields.<col>` | selector string or mapping | Column definitions, order is kept in the output |
| `fields.<col>.selector` | CSS selector | Relative to the record node; omit to use the node itself |
| `fields.<col>.attr` | string | Read an attribute (`href`, `title`, `class`, `data-*`) instead of text |
| `fields.<col>.html` | bool `false` | Return inner HTML |
| `fields.<col>.regex` | pattern | Applied to the raw value; first group or whole match is kept; no match -> `default` |
| `fields.<col>.type` | `str` / `int` / `float` | Conversion; numbers are extracted leniently (`"1,5 kg"` -> `1.5`) |
| `fields.<col>.multiple` | bool `false` | Collect all matches as a list (joined with `" \| "` in CSV/XLSX) |
| `fields.<col>.default` | any `null` | Value when nothing matches |
| `fields.<col>.absolute` | bool `false` | Resolve the value as a URL against the page URL |
| `detail.follow` | field name | List field holding the detail-page URL |
| `detail.fields` | mapping | Extra columns extracted from the detail page |
| `pagination.next_selector` | CSS selector | Link whose `href` leads to the next page |
| `pagination.url_pattern` | URL with `{page}` | Alternative: generate page URLs from a pattern (`start_page`, default 1) |
| `pagination.max_pages` | int `1` | Cap per start URL (override with `--max-pages`) |
| `pagination.stop_on_empty` | bool `true` | Stop when a page yields no records |
| `dedupe_key` | field name | Skip records whose key value was already seen |
| `respect_robots` | bool `true` | Check robots.txt before every request |
| `request.delay` / `jitter` | seconds `1.0` / `0.5` | Pause between requests (plus random jitter) |
| `request.retries` | int `3` | Attempts after the first one for 429/5xx/network errors |
| `request.retry_wait` / `backoff` | `1.0` / `2.0` | Wait before retry n = `retry_wait * backoff^(n-1)` (capped at 60 s, `Retry-After` wins) |
| `request.timeout` | seconds `15` | Per request |
| `request.user_agent` | string | Identify yourself - include a way to contact you |
| `request.headers` | mapping | Extra headers (e.g. `Accept-Language`) |

## Responsible scraping

This tool is built for **public, static pages whose owners allow automated access**. It deliberately does not include anything to work around access controls.

- **robots.txt** is fetched once per host and respected by default, including `Crawl-delay`. If the file cannot be loaded because of a server error, the host is treated as disallowed rather than ignoring its wishes. Disabling the check is a conscious, explicit action (`respect_robots: false` / `--ignore-robots`) that you should only take with the site owner's permission.
- **Rate limiting** is on by default (1 s + jitter) and retries back off exponentially. Keep the load far below what a human visitor would cause.
- **No circumvention**: no login automation, no CAPTCHA solving, no proxy rotation, no browser fingerprint spoofing. If a site requires any of that, it does not want to be scraped this way.
- **Personal data**: do not collect personal data (names, e-mail addresses, phone numbers, profiles) without a legal basis - in the EU this means the GDPR applies to you as the controller. Prefer aggregated, non-personal data such as prices, availability, specifications or public listings.
- **Terms of service and copyright** still apply to the extracted content. Check them before commercial use, and attribute sources where required.

## Limitations

- **Static HTML only.** Content rendered by JavaScript after page load is not visible to the parser. (A headless-browser mode is a natural extension; it is intentionally out of scope for this lightweight tool.)
- No form submission, session handling or API pagination tokens - jobs are stateless GET crawls.
- One job = one site structure. Sites that A/B-test their markup need selectors with fallbacks (`default`) or separate jobs.

## Running the tests

```bash
pip install -e ".[dev]"
python -m pytest -q          # 59 tests, all offline (httpx.MockTransport, HTML fixtures)
python -m compileall -q src
```

The test suite covers configuration validation, selectors and post-processing, pagination (both strategies), retry/backoff and `Retry-After`, robots.txt (allow, disallow, missing, unreachable, crawl-delay), de-duplication, every exporter, and the CLI.

## Project layout

```
src/web_scraper_toolkit/
  config.py      YAML loading & validation -> JobConfig
  fetcher.py     throttled, retrying HTTP client (httpx)
  robots.py      robots.txt policy with per-host cache
  extract.py     selectolax-based field extraction
  pagination.py  next-link / URL-pattern strategies
  scraper.py     crawl loop, detail pages, dedupe, statistics
  export.py      CSV / JSON / XLSX writers
  table.py       text table for previews
  cli.py         `scrape` entry point
examples/        books.yaml, quotes.yaml, output/books-sample.{csv,xlsx}
tests/           59 offline tests
```

## License

MIT - see `LICENSE`.

---

### Für deutschsprachige Kunden

Dieses Werkzeug extrahiert Daten aus statischen Webseiten (Produktlisten, Preise, Verfügbarkeiten, Verzeichnisse) und liefert sie als saubere CSV-, JSON- oder Excel-Datei. Ein Scraping-Auftrag ist eine kurze YAML-Datei - keine Programmierung nötig. Das Tool beachtet robots.txt, drosselt Anfragen und umgeht keine Logins oder Captchas. Personenbezogene Daten werden nur mit Rechtsgrundlage (DSGVO) erhoben. Gern richte ich einen Auftrag für Ihre Zielseite ein, liefere die Daten einmalig oder regelmäßig und dokumentiere die Konfiguration, damit Sie sie selbst weiterbetreiben können.
