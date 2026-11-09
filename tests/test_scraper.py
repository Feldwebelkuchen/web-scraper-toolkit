from web_scraper_toolkit.config import parse_job
from web_scraper_toolkit.scraper import Scraper

from conftest import BASE, list_page


def test_full_crawl_with_detail_pagination_dedupe_and_robots(site, job_dict, fetcher_factory, recorder):
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()

    # 5 items on two pages, one duplicate (alpha) -> 4 records
    titles = [r["title"] for r in result.records]
    assert titles == ["Alpha Book", "Beta Book", "Gamma Book", "Delta Book"]
    assert result.columns == ["title", "price", "stock", "rating", "tags", "url", "category", "upc"]

    alpha = result.records[0]
    assert alpha["price"] == 10.0
    assert alpha["stock"] == "In stock"
    assert alpha["rating"] == "Three"
    assert alpha["tags"] == ["t1", "x"]
    assert alpha["url"] == f"{BASE}/items/alpha.html"
    assert alpha["category"] == "Poetry" and alpha["upc"] == "UPC-A"

    # gamma's detail page is disallowed by robots.txt -> record kept, detail fields empty
    gamma = result.records[2]
    assert gamma["category"] is None and gamma["upc"] is None

    stats = result.stats
    assert stats.list_pages == 2
    assert stats.detail_pages == 3
    assert stats.duplicates == 1
    assert stats.blocked_by_robots == 1
    assert stats.records == 4
    assert len(stats.errors) == 1 and "robots" in stats.errors[0]
    assert f"{BASE}/robots.txt" in recorder.requests
    assert f"{BASE}/items/gamma.html" not in recorder.requests
    # the duplicate was detected before its detail page was fetched
    assert recorder.requests.count(f"{BASE}/items/alpha.html") == 1
    assert "4 records, 2 list pages, 3 detail pages" in stats.summary()


def test_max_pages_override_limits_pagination(site, job_dict, fetcher_factory):
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site), max_pages=1).run()
    assert result.stats.list_pages == 1
    assert [r["title"] for r in result.records] == ["Alpha Book", "Beta Book", "Gamma Book"]


def test_record_limit_stops_early(site, job_dict, fetcher_factory, recorder):
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site), limit=2).run()
    assert len(result.records) == 2
    assert f"{BASE}/catalogue/page-2.html" not in recorder.requests


def test_robots_disallow_blocks_list_page(site, job_dict, fetcher_factory, recorder):
    job_dict["start_urls"] = [f"{BASE}/private/page.html"]
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert result.records == []
    assert result.stats.blocked_by_robots == 1
    assert f"{BASE}/private/page.html" not in recorder.requests


def test_robots_can_be_disabled_explicitly(site, job_dict, fetcher_factory, recorder):
    job_dict["start_urls"] = [f"{BASE}/private/page.html"]
    job_dict["respect_robots"] = False
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert result.stats.blocked_by_robots == 0
    assert f"{BASE}/private/page.html" in recorder.requests
    assert f"{BASE}/robots.txt" not in recorder.requests


def test_missing_robots_txt_allows_everything(site, job_dict, fetcher_factory):
    del site[f"{BASE}/robots.txt"]
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert result.stats.blocked_by_robots == 0
    assert result.records[2]["upc"] == "UPC-G"


def test_unreachable_robots_txt_blocks_conservatively(site, job_dict, fetcher_factory, recorder):
    site[f"{BASE}/robots.txt"] = (503, "down")
    job_dict["request"]["retries"] = 0
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert result.records == []
    assert result.stats.blocked_by_robots == 1
    assert f"{BASE}/catalogue/page-1.html" not in recorder.requests


def test_crawl_delay_from_robots_slows_down(site, job_dict, fetcher_factory, recorder):
    site[f"{BASE}/robots.txt"] = "User-agent: *\nCrawl-delay: 2\n"
    job = parse_job(job_dict)
    fetcher = fetcher_factory(site)
    Scraper(job, fetcher=fetcher).run()
    assert fetcher.extra_delay == 2.0
    assert recorder.sleeps and all(s == 2.0 for s in recorder.sleeps)


def test_failed_list_page_is_recorded_as_error(site, job_dict, fetcher_factory):
    job_dict["start_urls"] = [f"{BASE}/missing.html", f"{BASE}/catalogue/page-2.html"]
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert len(result.stats.errors) == 1 and "HTTP 404" in result.stats.errors[0]
    assert [r["title"] for r in result.records] == ["Delta Book", "Alpha Book"]


def test_failed_detail_page_keeps_record(site, job_dict, fetcher_factory):
    del site[f"{BASE}/items/beta.html"]
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    beta = next(r for r in result.records if r["title"] == "Beta Book")
    assert beta["price"] == 20.5 and beta["category"] is None
    assert any("items/beta.html: HTTP 404" in e for e in result.stats.errors)


def test_url_pattern_pagination_stops_on_empty_page(job_dict, fetcher_factory, recorder):
    site = {
        f"{BASE}/robots.txt": (404, ""),
        f"{BASE}/p/1.html": list_page(1, [("a", "A Book", "1.00")], None),
        f"{BASE}/p/2.html": list_page(2, [("b", "B Book", "2.00")], None),
        f"{BASE}/p/3.html": list_page(3, [], None),
        f"{BASE}/p/4.html": list_page(4, [("d", "D Book", "4.00")], None),
    }
    del job_dict["start_urls"]
    del job_dict["detail"]
    job_dict["pagination"] = {"url_pattern": f"{BASE}/p/{{page}}.html", "max_pages": 10}
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    assert [r["title"] for r in result.records] == ["A Book", "B Book"]
    assert result.stats.list_pages == 3
    assert f"{BASE}/p/4.html" not in recorder.requests


def test_dedupe_on_detail_field(site, job_dict, fetcher_factory):
    # two distinct list entries point to detail pages with the same UPC
    site[f"{BASE}/items/delta.html"] = site[f"{BASE}/items/beta.html"]
    job_dict["dedupe_key"] = "upc"
    job = parse_job(job_dict)
    result = Scraper(job, fetcher=fetcher_factory(site)).run()
    upcs = [r["upc"] for r in result.records]
    assert upcs.count("UPC-B") == 1 and upcs.count("UPC-A") == 1
    assert result.stats.duplicates == 2  # delta (same UPC as beta) and the second alpha are dropped
    assert result.stats.detail_pages == 4  # detail-field dedupe can only happen after the fetch (gamma is blocked)
