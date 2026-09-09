"""حافظهٔ کانال — تاریخچهٔ پست‌ها برای جلوگیری از تکرار.

یک فایل JSON ساده که در ریپو commit می‌شود. هیچ دیتابیس خارجی لازم نیست.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MAX_POSTS = 400
FINGERPRINT_HISTORY = 120


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str) -> str:
    """یکسان‌سازی متن فارسی/عربی برای مقایسهٔ عنوان‌ها."""
    text = unicodedata.normalize("NFKC", text or "")
    table = str.maketrans(
        {
            "ي": "ی",
            "ك": "ک",
            "ة": "ه",
            "ۀ": "ه",
            "أ": "ا",
            "إ": "ا",
            "آ": "ا",
            "ؤ": "و",
            "ئ": "ی",
        }
    )
    text = text.translate(table)
    # نیم‌فاصله و فاصلهٔ چندگانه
    text = text.replace("\u200c", " ")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split()).lower()


def fingerprint(title: str, body: str = "") -> str:
    """اثر انگشت محتوا؛ برای تشخیص پست تکراری/بسیار شبیه."""
    key = _normalize(title)
    if body:
        # فقط ۳۰۰ کاراکتر اول بدنه — کافی برای تشخیص کپی مستقیم.
        key += "\n" + _normalize(body)[:300]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class PostRecord:
    ts: str
    format: str
    title: str
    topic_slug: str = ""
    fingerprint: str = ""
    message_id: int | None = None
    image_used: bool = False
    chars: int = 0
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PostRecord":
        allowed = {f for f in cls.__slots__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass(slots=True)
class Memory:
    posts: list[PostRecord] = field(default_factory=list)
    version: int = 2
    path: str = ""

    # ------------------------------------------------------------------ IO
    @classmethod
    def load(cls, path: str) -> "Memory":
        if not path or not os.path.exists(path):
            return cls(path=path)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("خواندن حافظه ممکن نشد (%s)؛ با حافظهٔ خالی ادامه می‌دهیم.", exc)
            return cls(path=path)

        posts = [PostRecord.from_dict(item) for item in raw.get("posts", []) if isinstance(item, dict)]
        return cls(posts=posts[-MAX_POSTS:], version=int(raw.get("version", 2)), path=path)

    def save(self) -> bool:
        if not self.path:
            return False
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            payload = {
                "version": self.version,
                "updated_at": utcnow().isoformat(),
                "posts": [p.to_dict() for p in self.posts[-MAX_POSTS:]],
            }
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
            return True
        except OSError as exc:
            logger.warning("ذخیرهٔ حافظه ممکن نشد: %s", exc)
            return False

    # --------------------------------------------------------------- query
    def add(self, record: PostRecord) -> None:
        self.posts.append(record)
        self.posts = self.posts[-MAX_POSTS:]

    def recent(self, n: int) -> list[PostRecord]:
        return self.posts[-n:]

    def recent_formats(self, n: int) -> list[str]:
        return [p.format for p in self.posts[-n:]]

    def is_duplicate(self, fp: str) -> bool:
        if not fp:
            return False
        window = self.posts[-FINGERPRINT_HISTORY:]
        return any(p.fingerprint == fp for p in window)

    def days_since_format(self, format_id: str) -> float | None:
        """چند روز از آخرین پست این قالب گذشته (None یعنی هیچ‌وقت)."""
        for post in reversed(self.posts):
            if post.format == format_id:
                try:
                    then = datetime.fromisoformat(post.ts)
                except ValueError:
                    return None
                if then.tzinfo is None:
                    then = then.replace(tzinfo=timezone.utc)
                return max(0.0, (utcnow() - then).total_seconds() / 86400.0)
        return None

    def titles_digest(self, n: int = 25) -> str:
        """فهرست عنوان‌های اخیر، برای دادن به مدل تا تکرار نکند."""
        lines = [f"- {p.title}" for p in self.posts[-n:]]
        return "\n".join(lines) if lines else "(هنوز پستی منتشر نشده)"

    def format_counts(self, n: int = 20) -> dict[str, int]:
        counts: dict[str, int] = {}
        for post in self.posts[-n:]:
            counts[post.format] = counts.get(post.format, 0) + 1
        return counts
