import csv

import pytest
import yaml

from web_scraper_toolkit import cli

from conftest import make_transport
from web_scraper_toolkit.config import RequestSpec
from web_scraper_toolkit.fetcher import Fetcher


def dump(data) -> str:
    return yaml.safe_dump(data, sort_keys=False)


@pytest.fixture
def job_file(tmp_path, job_dict):
    path = tmp_path / "job.yaml"
    path.write_text(dump(job_dict), encoding="utf-8")
    return path


@pytest.fixture
def offline(monkeypatch, site):
    """Route the CLI's fetcher to the mock site."""

    def make_fetcher(job):
        return Fetcher(RequestSpec(delay=0, jitter=0, retry_wait=0), transport=make_transport(site), sleep=lambda s: None)

    monkeypatch.setattr(cli, "make_fetcher", make_fetcher)


def test_validate_ok(job_file, capsys):
    assert cli.main(["validate", str(job_file)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "OK:" in out and "title, price, stock" in out and "respected" in out


def test_validate_reports_errors_with_exit_code_2(tmp_path, job_dict, capsys):
    del job_dict["fields"]
    path = tmp_path / "bad.yaml"
    path.write_text(dump(job_dict), encoding="utf-8")
    assert cli.main(["validate", str(path)]) == cli.EXIT_CONFIG
    assert "'fields' must be a non-empty mapping" in capsys.readouterr().err


def test_run_writes_csv_and_reports_partial_errors(job_file, offline, tmp_path, capsys):
    out = tmp_path / "out.csv"
    code = cli.main(["run", str(job_file), "--out", str(out), "-q"])
    assert code == cli.EXIT_PARTIAL  # gamma's detail page is blocked by robots.txt
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4 and rows[0]["upc"] == "UPC-A"
    err = capsys.readouterr().err
    assert "wrote 4 records" in err and "summary:" in err


def test_run_exit_ok_without_errors(job_file, offline, tmp_path, site):
    del site["https://example.test/robots.txt"]
    out = tmp_path / "out.json"
    assert cli.main(["run", str(job_file), "--out", str(out), "-q"]) == cli.EXIT_OK


def test_run_exports_one_crawl_to_several_files(job_file, offline, tmp_path, site):
    del site["https://example.test/robots.txt"]
    xlsx, csv_path = tmp_path / "out.xlsx", tmp_path / "out.csv"
    code = cli.main(["run", str(job_file), "--out", str(xlsx), "--out", str(csv_path), "-q"])
    assert code == cli.EXIT_OK
    assert xlsx.exists() and csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").count("\n") == 5  # header + 4 records


def test_run_rejects_unknown_extension(job_file, offline, tmp_path, capsys):
    assert cli.main(["run", str(job_file), "--out", str(tmp_path / "out.txt")]) == cli.EXIT_CONFIG
    assert "cannot infer format" in capsys.readouterr().err


def test_run_no_records_exit_code(job_file, offline, tmp_path, job_dict, site):
    job_dict["list_selector"] = "div.does-not-exist"
    job_file.write_text(dump(job_dict), encoding="utf-8")
    assert cli.main(["run", str(job_file), "--out", str(tmp_path / "o.csv"), "-q"]) == cli.EXIT_NO_DATA


def test_sample_prints_table(job_file, offline, capsys):
    code = cli.main(["sample", str(job_file), "--pages", "1", "--limit", "2", "-q"])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "| title" in out and "Alpha Book" in out and "Beta Book" in out and "Gamma Book" not in out
