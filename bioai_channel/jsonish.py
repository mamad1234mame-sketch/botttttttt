"""پارسر تحمل‌پذیر JSON برای خروجی مدل.

مدل‌ها گاهی خروجی را داخل ```json ... ``` می‌گذارند، گاهی یک کاما اضافه
می‌کنند، گاهی بعد از JSON توضیح می‌نویسند. اینجا همهٔ این حالت‌ها را
مدیریت می‌کنیم تا pipeline نشکند.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.+?)```", re.DOTALL)


class JsonParseError(ValueError):
    pass


def extract_json(text: str) -> Any:
    """اولین شیء/آرایهٔ JSON معتبر را از متن بیرون می‌کشد."""
    if not text or not text.strip():
        raise JsonParseError("خروجی مدل خالی بود.")

    candidates: list[str] = []

    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1).strip())
    candidates.append(text.strip())

    # بزرگ‌ترین بلوک متعادل { } یا [ ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

    errors: list[str] = []
    for candidate in candidates:
        for attempt in (candidate, _repair(candidate)):
            try:
                return json.loads(attempt)
            except json.JSONDecodeError as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    raise JsonParseError("هیچ JSON معتبری در خروجی مدل پیدا نشد. آخرین خطا: " + errors[-1])


def _repair(text: str) -> str:
    """تلاش سبک برای درست‌کردن خطاهای رایج."""
    text = text.strip()
    # کامای معلق قبل از } یا ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    # نقل‌قول‌های هوشمند
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return text


def coerce_str_list(value: Any, limit: int = 12) -> list[str]:
    """هر چیزی را به فهرستی از رشته‌های تمیز تبدیل می‌کند."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict):
                # مثال: {"title": ..., "url": ...}
                url = str(item.get("url") or item.get("link") or "").strip()
                title = str(item.get("title") or item.get("name") or "").strip()
                items.append(f"{title} — {url}" if title and url else (title or url))
            else:
                items.append(str(item))
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        item = " ".join(str(item).split())
        if item and item.lower() not in seen:
            seen.add(item.lower())
            cleaned.append(item)
        if len(cleaned) >= limit:
            break
    return cleaned
