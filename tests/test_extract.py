import re

from web_scraper_toolkit.config import FieldSpec
from web_scraper_toolkit.extract import convert, extract_field, extract_record, parse_html, select_items

HTML = """
<article class="card">
  <h3><a href="../items/alpha.html" title="Alpha Book">Alpha...</a></h3>
  <p class="price">£51.77</p>
  <p class="stock">
      In stock   (22 available)
  </p>
  <p class="rating Three"></p>
  <div class="tags"><a class="tag">poetry</a><a class="tag">classic</a></div>
</article>
"""


def node():
    return select_items(parse_html(HTML), "article.card")[0]


def test_text_is_whitespace_normalised():
    assert extract_field(node(), FieldSpec("stock", ".stock"), "https://x.test/") == "In stock (22 available)"


def test_attribute_extraction():
    assert extract_field(node(), FieldSpec("title", "h3 a", attr="title"), "https://x.test/") == "Alpha Book"


def test_regex_group_and_float_type():
    spec = FieldSpec("price", ".price", regex=re.compile(r"([0-9.]+)"), type="float")
    assert extract_field(node(), spec, "https://x.test/") == 51.77


def test_regex_without_group_uses_whole_match():
    spec = FieldSpec("rating", ".rating", attr="class", regex=re.compile(r"Three|Four"))
    assert extract_field(node(), spec, "https://x.test/") == "Three"


def test_regex_no_match_returns_default():
    spec = FieldSpec("n", ".stock", regex=re.compile(r"\d{5}"), default="n/a")
    assert extract_field(node(), spec, "https://x.test/") == "n/a"


def test_missing_selector_returns_default():
    assert extract_field(node(), FieldSpec("x", ".nope"), "https://x.test/") is None
    assert extract_field(node(), FieldSpec("x", ".nope", default=0), "https://x.test/") == 0


def test_multiple_collects_all_matches():
    assert extract_field(node(), FieldSpec("tags", ".tag", multiple=True), "https://x.test/") == ["poetry", "classic"]
    assert extract_field(node(), FieldSpec("none", ".nope", multiple=True), "https://x.test/") == []


def test_absolute_url_resolution():
    spec = FieldSpec("url", "h3 a", attr="href", absolute=True)
    assert extract_field(node(), spec, "https://x.test/catalogue/page-1.html") == "https://x.test/items/alpha.html"


def test_html_extraction():
    value = extract_field(node(), FieldSpec("h", "h3", html=True), "https://x.test/")
    assert value.startswith("<h3>") and "Alpha Book" in value


def test_extract_record_keeps_field_order():
    fields = [FieldSpec("title", "h3 a", attr="title"), FieldSpec("price", ".price", type="float")]
    record = extract_record(node(), fields, "https://x.test/")
    assert list(record) == ["title", "price"]
    assert record["price"] == 51.77  # forgiving numeric conversion strips the currency sign


def test_convert_is_forgiving_for_numbers():
    assert convert("1,5 kg", "float") == 1.5
    assert convert("42", "int") == 42
    assert convert("approx. 12 pieces", "int") == 12
    assert convert("no digits", "float") is None
    assert convert("", "int") is None
    assert convert("keep me", "str") == "keep me"
