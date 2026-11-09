import copy

import pytest
import yaml

from web_scraper_toolkit.config import ConfigError, load_job, parse_job


def test_parse_valid_job(job_dict):
    job = parse_job(job_dict)
    assert job.name == "test-job"
    assert [f.name for f in job.fields] == ["title", "price", "stock", "rating", "tags", "url"]
    assert job.detail is not None and job.detail.follow == "url"
    assert job.columns == ["title", "price", "stock", "rating", "tags", "url", "category", "upc"]
    assert job.pagination.max_pages == 5
    assert job.respect_robots is True


def test_shorthand_field_is_a_selector(job_dict):
    job = parse_job(job_dict)
    stock = next(f for f in job.fields if f.name == "stock")
    assert stock.selector == ".stock" and stock.attr is None and stock.regex is None


def test_missing_list_selector_is_reported(job_dict):
    del job_dict["list_selector"]
    with pytest.raises(ConfigError, match="list_selector"):
        parse_job(job_dict)


def test_errors_are_collected_together(job_dict):
    del job_dict["list_selector"]
    job_dict["fields"]["price"]["regex"] = "(["
    job_dict["pagination"]["max_pages"] = 0
    job_dict["bogus"] = 1
    with pytest.raises(ConfigError) as info:
        parse_job(job_dict)
    message = str(info.value)
    assert "list_selector" in message
    assert "invalid regex" in message
    assert "max_pages" in message
    assert "unknown option(s): bogus" in message


def test_dedupe_key_must_reference_a_field(job_dict):
    job_dict["dedupe_key"] = "nope"
    with pytest.raises(ConfigError, match="dedupe_key"):
        parse_job(job_dict)


def test_detail_follow_must_reference_list_field(job_dict):
    job_dict["detail"]["follow"] = "category"
    with pytest.raises(ConfigError, match="detail.follow"):
        parse_job(job_dict)


def test_pagination_strategies_are_exclusive(job_dict):
    job_dict["pagination"]["url_pattern"] = "https://example.test/p/{page}"
    with pytest.raises(ConfigError, match="either 'next_selector' or 'url_pattern'"):
        parse_job(job_dict)


def test_url_pattern_without_start_urls_is_allowed(job_dict):
    del job_dict["start_urls"]
    job_dict["pagination"] = {"url_pattern": "https://example.test/p/{page}", "max_pages": 2}
    job = parse_job(job_dict)
    assert job.start_urls == ()
    assert job.pagination.url_pattern == "https://example.test/p/{page}"


def test_start_urls_must_be_http(job_dict):
    job_dict["start_urls"] = ["ftp://example.test/x"]
    with pytest.raises(ConfigError, match="http"):
        parse_job(job_dict)


def test_load_job_from_yaml_file(tmp_path, job_dict):
    path = tmp_path / "job.yaml"
    path.write_text(yaml.safe_dump(job_dict, sort_keys=False), encoding="utf-8")
    job = load_job(path)
    assert job.name == "test-job"
    assert [f.name for f in job.fields] == ["title", "price", "stock", "rating", "tags", "url"]


def test_load_job_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_job(tmp_path / "nope.yaml")


def test_load_job_invalid_yaml(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("fields: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_job(path)


def test_request_defaults_and_validation(job_dict):
    del job_dict["request"]
    job = parse_job(job_dict)
    assert job.request.delay == 1.0 and job.request.retries == 3
    bad = copy.deepcopy(job_dict)
    bad["request"] = {"retries": -1, "timeout": "slow"}
    with pytest.raises(ConfigError) as info:
        parse_job(bad)
    assert "request.retries" in str(info.value) and "request.timeout" in str(info.value)
