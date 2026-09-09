"""گرفتن سیگنال‌های زنده از منابع عمومی و رایگان.

هر منبع کاملاً optional است: اگر شکست خورد، لاگ می‌شود و بقیه ادامه
می‌یابند. هیچ‌وقت کل اجرا به‌خاطر یک RSS از کار نمی‌افتد.

منابع:
  - Google Trends RSS (ترندهای داغ جهان/ایران/آمریکا)
  - PubMed E-utilities (مقالات تازه)
  - bioRxiv API (پیش‌چاپ‌های تازه)
"""

from __future__ import annotations

import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote

import requests

from .content.sources import BIORXIV_CATEGORIES, PUBMED_QUERIES

logger = logging.getLogger(__name__)

USER_AGENT = "bioai-channel/1.0 (Telegram science channel; contact: channel admin)"

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BIORXIV_BASE = "https://api.biorxiv.org"

#: NCBI E-utilities بدون کلید API فقط ۳ درخواست بر ثانیه اجازه می‌دهد.
#: با کلید رایگان NCBI این سقف به ۱۰ می‌رسد.
MIN_REQUEST_INTERVAL = 0.35
_last_request_at = 0.0


def _throttle() -> None:
    """فاصلهٔ حداقلی بین درخواست‌ها را رعایت می‌کند."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def _get(session: requests.Session, url: str, params: dict | None = None, timeout: int = 15):
    """GET با throttle و retry روی ۴۲۹/۵۰۳."""
    attempt = 0
    while True:
        attempt += 1
        _throttle()
        try:
            response = session.get(url, params=params, timeout=timeout)
        except requests.RequestException:
            if attempt >= 3:
                raise
            time.sleep(1.0 * attempt)
            continue

        if response.status_code in {429, 503} and attempt < 3:
            wait = 1.0 * attempt
            logger.debug("HTTP %d از %s؛ %.1fs صبر می‌کنیم", response.status_code, url, wait)
            time.sleep(wait)
            continue
        return response


def _ncbi_params(params: dict) -> dict:
    """اگر کلید NCBI تنظیم شده باشد اضافه‌اش کن (سقف ۳ → ۱۰ درخواست/ثانیه)."""
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    if api_key:
        return {**params, "api_key": api_key}
    return params


@dataclass(slots=True)
class Signal:
    source: str
    title: str
    url: str = ""
    detail: str = ""

    def as_line(self) -> str:
        base = f"[{self.source}] {self.title}"
        if self.url:
            base += f" — {self.url}"
        if self.detail:
            base += f"\n    {self.detail}"
        return base


@dataclass(slots=True)
class SignalBundle:
    trends: list[Signal] = field(default_factory=list)
    pubmed: list[Signal] = field(default_factory=list)
    biorxiv: list[Signal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def all_signals(self) -> list[Signal]:
        return [*self.trends, *self.pubmed, *self.biorxiv]

    def is_empty(self) -> bool:
        return not self.all_signals()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return session


# --------------------------------------------------------------------------
# Google Trends
# --------------------------------------------------------------------------

def fetch_trends(
    regions: tuple[str, ...] = ("US", "IR"),
    limit: int = 10,
    timeout: int = 12,
) -> tuple[list[Signal], list[str]]:
    """RSS ترندهای روزانهٔ گوگل. بدون کلید API."""
    signals: list[Signal] = []
    errors: list[str] = []
    session = _session()

    for region in regions:
        url = f"https://trends.google.com/trending/rss?geo={quote(region)}"
        try:
            response = _get(session, url, timeout=timeout)
            if not response.ok:
                errors.append(f"trends[{region}]: HTTP {response.status_code}")
                continue
            root = ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError) as exc:
            errors.append(f"trends[{region}]: {type(exc).__name__}: {exc}")
            continue

        count = 0
        for item in root.iter("item"):
            if count >= limit:
                break
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            traffic = ""
            for child in item:
                if child.tag.endswith("approx_traffic"):
                    traffic = (child.text or "").strip()
            if not title:
                continue
            detail = f"حجم جست‌وجو: {traffic}" if traffic else ""
            signals.append(Signal(source=f"GoogleTrends/{region}", title=title, url=link, detail=detail))
            count += 1

    return signals, errors


# --------------------------------------------------------------------------
# PubMed
# --------------------------------------------------------------------------

def fetch_pubmed(
    queries: tuple[str, ...] = PUBMED_QUERIES,
    per_query: int = 4,
    days_back: int = 10,
    timeout: int = 15,
) -> tuple[list[Signal], list[str]]:
    """مقالات تازه از PubMed E-utilities.

    نکتهٔ مهم: فیلتر تاریخ باید با پارامترهای `reldate` و `datetype=pdat`
    داده شود، نه داخل خودِ `term`. اگر داخل term بگذاری، eutils بی‌صدا
    نتیجهٔ خالی برمی‌گرداند.
    """
    signals: list[Signal] = []
    errors: list[str] = []
    session = _session()

    for query in queries:
        params = _ncbi_params({
            "db": "pubmed",
            "term": query,
            "retmax": str(per_query),
            "sort": "date",
            "retmode": "json",
            "reldate": str(days_back),
            "datetype": "pdat",
        })
        try:
            search = _get(session, f"{PUBMED_BASE}/esearch.fcgi", params=params, timeout=timeout)
            search.raise_for_status()
            ids = search.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                continue

            summary_params = _ncbi_params({
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "xml",
            })
            summary = _get(session, f"{PUBMED_BASE}/esummary.fcgi", params=summary_params, timeout=timeout)
            summary.raise_for_status()
            root = ET.fromstring(summary.content)
        except (requests.RequestException, ET.ParseError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"pubmed[{query[:28]}…]: {type(exc).__name__}: {exc}")
            continue

        for doc in root.iter("DocSum"):
            # نکتهٔ مهم: در پاسخ واقعی، PMID یک المنت <Id> مستقیم زیر DocSum
            # است، نه <Item Name="Id">. اگر دنبال Item بگردی، بی‌صدا هیچی
            # پیدا نمی‌کنی.
            pmid = (doc.findtext("Id") or "").strip()
            title = ""
            source = ""
            pub_date = ""
            for item in doc.iter("Item"):
                name = item.get("Name", "")
                if name == "Title":
                    title = (item.text or "").strip()
                elif name == "Source":
                    source = (item.text or "").strip()
                elif name == "PubDate":
                    pub_date = (item.text or "").strip()
            if not pmid or not title:
                continue
            detail = " · ".join(x for x in (source, pub_date) if x)
            signals.append(
                Signal(
                    source="PubMed",
                    title=title,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    detail=detail,
                )
            )

    return signals, errors


# --------------------------------------------------------------------------
# bioRxiv
# --------------------------------------------------------------------------

def fetch_biorxiv(
    categories: tuple[str, ...] = BIORXIV_CATEGORIES,
    per_category: int = 3,
    days_back: int = 6,
    timeout: int = 15,
    page_size: int = 60,
    max_pages: int = 3,
) -> tuple[list[Signal], list[str]]:
    """پیش‌چاپ‌های تازه از bioRxiv.

    نکتهٔ مهم: endpoint `/details/biorxiv/...` پارامتر category را در URL
    نمی‌پذیرد (۴۰۴ می‌دهد). باید فهرست را گرفت و روی فیلد `category` هر
    رکورد فیلتر کرد. نام دسته‌ها هم انسان‌خوان و با فاصله است،
    مثلاً `synthetic biology` نه `synthetic-biology`.
    """
    signals: list[Signal] = []
    errors: list[str] = []
    session = _session()

    wanted = {c.strip().lower() for c in categories}
    per_wanted: dict[str, int] = {c: 0 for c in wanted}

    today = date.today()
    start = date.fromordinal(today.toordinal() - days_back).isoformat()
    end = today.isoformat()

    entries: list[dict] = []
    cursor = 0
    for page in range(max_pages):
        url = f"{BIORXIV_BASE}/details/biorxiv/{start}/{end}/{cursor}/{page_size}"
        try:
            response = _get(session, url, timeout=timeout)
            if not response.ok:
                errors.append(f"biorxiv: HTTP {response.status_code} (cursor={cursor})")
                break
            payload = response.json()
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"biorxiv: {type(exc).__name__}: {exc}")
            break

        batch = payload.get("collection") or []
        entries.extend(batch)

        messages = payload.get("messages") or [{}]
        total = int(messages[0].get("total", 0) or 0)
        cursor += len(batch)
        if not batch or cursor >= total:
            break

    for entry in entries:
        category = str(entry.get("category", "")).strip().lower()
        if category not in wanted or per_wanted[category] >= per_category:
            continue
        title = str(entry.get("title", "")).strip()
        if not title:
            continue
        doi = str(entry.get("doi", "")).strip()
        server = str(entry.get("server", "bioRxiv")).strip()
        signals.append(
            Signal(
                source=f"bioRxiv/{category}",
                title=title,
                url=f"https://doi.org/{doi}" if doi else "",
                detail=f"preprint ({server})",
            )
        )
        per_wanted[category] += 1

    return signals, errors


# --------------------------------------------------------------------------
# جمع‌کننده
# --------------------------------------------------------------------------

def gather(
    regions: tuple[str, ...] = ("US", "IR"),
    max_items: int = 12,
    timeout: int = 12,
    include_pubmed: bool = True,
    include_biorxiv: bool = True,
) -> SignalBundle:
    bundle = SignalBundle()

    bundle.trends, errors = fetch_trends(regions=regions, limit=8, timeout=timeout)
    bundle.errors.extend(errors)

    if include_pubmed:
        bundle.pubmed, errors = fetch_pubmed(per_query=3, timeout=timeout + 3)
        bundle.errors.extend(errors)

    if include_biorxiv:
        bundle.biorxiv, errors = fetch_biorxiv(per_category=3, timeout=timeout + 3)
        bundle.errors.extend(errors)

    # سقف کلی
    bundle.trends = bundle.trends[:max_items]
    bundle.pubmed = bundle.pubmed[:max_items]
    bundle.biorxiv = bundle.biorxiv[:max_items]

    logger.info(
        "سیگنال‌ها: %d ترند، %d PubMed، %d bioRxiv (%d خطا)",
        len(bundle.trends),
        len(bundle.pubmed),
        len(bundle.biorxiv),
        len(bundle.errors),
    )
    return bundle


def as_prompt_block(bundle: SignalBundle, max_lines: int = 26) -> str:
    """سیگنال‌ها را به یک بلوک متنی برای پرامپت تبدیل می‌کند."""
    if bundle.is_empty():
        return (
            "LIVE SIGNALS: none available in this run.\n"
            "You must still search the web yourself before writing.\n"
        )

    lines: list[str] = []
    for signal in bundle.all_signals()[:max_lines]:
        lines.append("- " + signal.as_line())

    header = (
        "LIVE SIGNALS fetched minutes ago (raw material — react to them, "
        "do not just list them):\n"
    )
    if bundle.errors:
        header += f"(note: {len(bundle.errors)} source(s) failed this run)\n"
    return header + "\n".join(lines) + "\n"


__all__ = [
    "Signal",
    "SignalBundle",
    "fetch_trends",
    "fetch_pubmed",
    "fetch_biorxiv",
    "gather",
    "as_prompt_block",
]
