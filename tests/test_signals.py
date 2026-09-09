"""تست گرفتن سیگنال‌ها با HTTP جعلی."""

from __future__ import annotations

import json

import pytest
import requests

from bioai_channel import signals

TRENDS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com">
  <channel>
    <item>
      <title>AlphaFold</title>
      <link>https://trends.google.com/trending?geo=US</link>
      <ht:approx_traffic>200,000+</ht:approx_traffic>
    </item>
    <item><title></title></item>
  </channel>
</rss>"""

# شکل واقعی پاسخ esummary: PMID یک المنت <Id> مستقیم زیر DocSum است،
# و بقیهٔ فیلدها <Item Name="..."> هستند. (نه <Item Name="Id">!)
ESUMMARY_XML = """<?xml version="1.0"?>
<eSummaryResult>
  <DocSum>
    <Id>12345678</Id>
    <Item Name="PubDate" Type="Date">2026 Sep 1</Item>
    <Item Name="Source" Type="String">Nature</Item>
    <Item Name="Title" Type="String">A deep learning method for protein design</Item>
  </DocSum>
</eSummaryResult>"""


class FakeResponse:
    def __init__(self, content=None, json_data=None, status_code=200):
        self.content = content or b""
        self._json = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = content.decode() if content else ""

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.calls: list[str] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        return self.handler(url, params)


@pytest.fixture
def patch_session(monkeypatch):
    def _patch(handler):
        session = FakeSession(handler)
        monkeypatch.setattr(signals, "_session", lambda: session)
        return session

    return _patch


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """throttle و sleep واقعی را در تست‌ها خاموش می‌کند تا سریع بمانند.

    خودِ throttle در test_throttle_spaces_out_requests جداگانه بررسی می‌شود
    (آنجا sleep دوباره patch می‌شود).
    """
    monkeypatch.setattr(signals, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(signals.time, "sleep", lambda *_: None)


def test_fetch_trends_parses_rss(patch_session):
    patch_session(lambda url, params: FakeResponse(content=TRENDS_XML.encode()))
    items, errors = signals.fetch_trends(regions=("US",), limit=5)
    assert errors == []
    assert len(items) == 1
    assert items[0].title == "AlphaFold"
    assert "GoogleTrends/US" in items[0].source
    assert "200,000+" in items[0].detail


def test_fetch_trends_handles_http_error(patch_session):
    patch_session(lambda url, params: FakeResponse(status_code=404))
    items, errors = signals.fetch_trends(regions=("IR",))
    assert items == []
    assert len(errors) == 1 and "404" in errors[0]


def test_fetch_trends_handles_malformed_xml(patch_session):
    patch_session(lambda url, params: FakeResponse(content=b"<not><closed"))
    items, errors = signals.fetch_trends(regions=("US",))
    assert items == []
    assert errors


def test_fetch_pubmed_parses_summary(patch_session):
    def handler(url, params):
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["12345678"]}})
        return FakeResponse(content=ESUMMARY_XML.encode())

    patch_session(handler)
    items, errors = signals.fetch_pubmed(queries=("cancer AND ai",), per_query=3)
    assert errors == []
    assert items[0].title.startswith("A deep learning")
    assert items[0].url.endswith("12345678/")
    assert "Nature" in items[0].detail


def test_fetch_pubmed_uses_reldate_param_not_term_filter(patch_session):
    """رگرسیون: فیلتر تاریخ داخل `term` باعث نتیجهٔ خالی بی‌صدا می‌شد."""
    seen: list[dict] = []

    def handler(url, params):
        seen.append(dict(params or {}))
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["1"]}})
        return FakeResponse(content=ESUMMARY_XML.encode())

    patch_session(handler)
    signals.fetch_pubmed(queries=("ai AND protein",), days_back=10)

    search_params = seen[0]
    assert search_params["reldate"] == "10"
    assert search_params["datetype"] == "pdat"
    assert "[PDAT]" not in search_params["term"]
    assert "last" not in search_params["term"]


def test_fetch_pubmed_no_results(patch_session):
    patch_session(lambda url, params: FakeResponse(json_data={"esearchresult": {"idlist": []}}))
    items, errors = signals.fetch_pubmed(queries=("nothing",))
    assert items == []
    assert errors == []


def test_fetch_pubmed_handles_network_error(patch_session):
    def handler(url, params):
        raise requests.ConnectionError("boom")

    patch_session(handler)
    items, errors = signals.fetch_pubmed(queries=("x",))
    assert items == []
    assert errors and "ConnectionError" in errors[0]


def test_fetch_biorxiv_parses_collection(patch_session):
    payload = {
        "messages": [{"status": "ok", "total": "2"}],
        "collection": [
            {
                "title": "Spatial transformer for scRNA-seq",
                "doi": "10.1101/2026.01.01.1",
                "server": "bioRxiv",
                "category": "bioinformatics",
            },
            {
                "title": "Not in a wanted category",
                "doi": "10.1101/x",
                "server": "bioRxiv",
                "category": "ecology",
            },
        ],
    }
    patch_session(lambda url, params: FakeResponse(json_data=payload))
    items, errors = signals.fetch_biorxiv(categories=("bioinformatics",), per_category=2)
    assert errors == []
    assert len(items) == 1  # رکورد ecology فیلتر می‌شود
    assert items[0].title.startswith("Spatial transformer")
    assert items[0].url == "https://doi.org/10.1101/2026.01.01.1"
    assert items[0].source == "bioRxiv/bioinformatics"


def test_fetch_biorxiv_url_has_no_category_segment(patch_session):
    """endpoint واقعی bioRxiv پارامتر دسته در URL را ۴۰۴ می‌دهد."""
    seen: list[str] = []

    def handler(url, params):
        seen.append(url)
        return FakeResponse(json_data={"messages": [{"total": "0"}], "collection": []})

    patch_session(handler)
    signals.fetch_biorxiv(categories=("genomics",))
    assert seen, "هیچ درخواستی زده نشد"
    for url in seen:
        assert "/details/biorxiv/genomics/" not in url
        assert "/details/biorxiv/" in url


def test_fetch_biorxiv_respects_per_category_cap(patch_session):
    entries = [
        {"title": f"paper {i}", "doi": f"10.1101/{i}", "category": "bioinformatics", "server": "bioRxiv"}
        for i in range(10)
    ]
    patch_session(
        lambda url, params: FakeResponse(
            json_data={"messages": [{"total": "10"}], "collection": entries}
        )
    )
    items, _errors = signals.fetch_biorxiv(categories=("bioinformatics",), per_category=3)
    assert len(items) == 3


def test_fetch_biorxiv_category_names_use_spaces():
    """نام دسته‌های پیکربندی باید با پاسخ واقعی API یکی باشند."""
    from bioai_channel.content.sources import BIORXIV_CATEGORIES

    for name in BIORXIV_CATEGORIES:
        assert not name.startswith("-")
        assert name == name.strip().lower()
    assert "bioinformatics" in BIORXIV_CATEGORIES
    assert "synthetic biology" in BIORXIV_CATEGORIES


def test_fetch_biorxiv_handles_http_error(patch_session):
    patch_session(lambda url, params: FakeResponse(status_code=500))
    items, errors = signals.fetch_biorxiv(categories=("genomics",))
    assert items == []
    assert errors and "500" in errors[0]


def test_gather_is_resilient(patch_session):
    def handler(url, params):
        if "trends" in url:
            return FakeResponse(content=TRENDS_XML.encode())
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["1"]}})
        if "esummary" in url:
            return FakeResponse(content=ESUMMARY_XML.encode())
        return FakeResponse(json_data={"collection": []})

    patch_session(handler)
    bundle = signals.gather(regions=("US",), max_items=5)
    assert not bundle.is_empty()
    assert len(bundle.trends) == 1
    # هر ۵ کوئری PubMed یک نتیجه می‌دهند
    assert len(bundle.pubmed) == 5
    assert bundle.biorxiv == []


def test_as_prompt_block_when_empty():
    block = signals.as_prompt_block(signals.SignalBundle())
    assert "none available" in block


def test_as_prompt_block_lists_signals():
    bundle = signals.SignalBundle(trends=[signals.Signal("GoogleTrends/US", "CRISPR", "https://t")])
    block = signals.as_prompt_block(bundle)
    assert "CRISPR" in block
    assert "LIVE SIGNALS" in block


def test_bundle_all_signals_order():
    bundle = signals.SignalBundle(
        trends=[signals.Signal("t", "1")],
        pubmed=[signals.Signal("p", "2")],
        biorxiv=[signals.Signal("b", "3")],
    )
    assert [s.title for s in bundle.all_signals()] == ["1", "2", "3"]


def test_gather_records_errors_without_raising(patch_session):
    def handler(url, params):
        raise requests.Timeout("slow")

    patch_session(handler)
    bundle = signals.gather(regions=("US",))
    assert bundle.is_empty()
    assert len(bundle.errors) >= 3


def test_ncbi_rate_limit_is_retried(monkeypatch, patch_session):
    """رگرسیون: E-utilities بدون throttle با ۴۲۹ جواب می‌داد."""
    slept: list[float] = []
    monkeypatch.setattr(signals.time, "sleep", lambda s: slept.append(s))

    calls = {"n": 0}

    def handler(url, params):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(status_code=429)
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["1"]}})
        return FakeResponse(content=ESUMMARY_XML.encode())

    patch_session(handler)
    items, errors = signals.fetch_pubmed(queries=("ai AND protein",), per_query=2)
    assert errors == []
    assert len(items) == 1
    assert calls["n"] >= 2


def test_throttle_spaces_out_requests(monkeypatch, patch_session):
    """بین درخواست‌ها باید فاصلهٔ حداقلی رعایت شود."""
    monkeypatch.setattr(signals, "MIN_REQUEST_INTERVAL", 0.35)  # فیکسچر fast را لغو کن
    monkeypatch.setattr(signals, "_last_request_at", 0.0)
    slept: list[float] = []
    monkeypatch.setattr(signals.time, "sleep", lambda s: slept.append(s))
    patch_session(lambda url, params: FakeResponse(status_code=500))

    signals.fetch_trends(regions=("US", "IR", "GB"), limit=2)
    # برای ۳ منطقه، حداقل ۲ بار throttle باید خوابیده باشد
    assert len(slept) >= 2
    assert all(s <= signals.MIN_REQUEST_INTERVAL + 0.001 for s in slept)


def test_ncbi_api_key_is_forwarded(monkeypatch, patch_session):
    monkeypatch.setenv("NCBI_API_KEY", "my-ncbi-key")
    seen: list[dict] = []

    def handler(url, params):
        seen.append(dict(params or {}))
        return FakeResponse(json_data={"esearchresult": {"idlist": []}})

    patch_session(handler)
    signals.fetch_pubmed(queries=("x",))
    assert seen and seen[0].get("api_key") == "my-ncbi-key"


def test_ncbi_api_key_absent_by_default(monkeypatch, patch_session):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    seen: list[dict] = []

    def handler(url, params):
        seen.append(dict(params or {}))
        return FakeResponse(json_data={"esearchresult": {"idlist": []}})

    patch_session(handler)
    signals.fetch_pubmed(queries=("x",))
    assert "api_key" not in seen[0]


def test_pubmed_pmid_comes_from_Id_element_not_Item(patch_session):
    """رگرسیون: PMID در <Id> است نه <Item Name="Id">؛ قبلاً بی‌صدا صفر می‌شد."""
    xml_with_item_id = """<?xml version="1.0"?>
<eSummaryResult><DocSum>
  <Item Name="Id">999</Item>
  <Item Name="Title">should be skipped</Item>
</DocSum></eSummaryResult>"""

    def handler(url, params):
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["999"]}})
        return FakeResponse(content=xml_with_item_id.encode())

    patch_session(handler)
    items, errors = signals.fetch_pubmed(queries=("x",))
    # بدون <Id> واقعی، رکورد باید رد شود (نه اینکه با pmid خالی ساخته شود)
    assert items == []
    assert errors == []

    # و با <Id> واقعی باید کار کند
    def handler2(url, params):
        if "esearch" in url:
            return FakeResponse(json_data={"esearchresult": {"idlist": ["12345678"]}})
        return FakeResponse(content=ESUMMARY_XML.encode())

    patch_session(handler2)
    items2, _ = signals.fetch_pubmed(queries=("x",))
    assert len(items2) == 1
    assert items2[0].url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
