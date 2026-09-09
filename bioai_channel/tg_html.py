"""سانیتایزر HTML برای تلگرام.

مشکل اصلی: با parse_mode=HTML، هر `<` یا `>` یا `&` نامعتبر باعث
`400 Bad Request: can't parse entities` می‌شود و **کل پیام** رد می‌شود.
متن علمی فارسی پر از `p < 0.05` و `&` است، پس باید خودمان کنترل کنیم.

راه‌حل: فقط تگ‌های مجاز تلگرام را نگه می‌داریم، بقیهٔ `<`/`>`/`&`ها را
escape می‌کنیم، و تگ‌های بسته‌نشده را حذف می‌کنیم.
"""

from __future__ import annotations

import re
from html import escape, unescape

#: تگ‌هایی که تلگرام با parse_mode=HTML می‌شناسد (و ما اجازه می‌دهیم).
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "b", "strong",
        "i", "em",
        "u", "ins",
        "s", "strike", "del",
        "span",
        "tg-spoiler",
        "tg-emoji",
        "a",
        "code",
        "pre",
        "blockquote",
    }
)

#: تگ‌هایی که باید با محتوایشان حذف شوند (نه فقط تگ).
DROP_WITH_CONTENT: frozenset[str] = frozenset({"script", "style"})

_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)\s*([^>]*?)\s*(/?)\s*>")
_ALLOWED_ATTRS = {"href", "emoji-id"}
_ATTR_RE = re.compile(r"""([a-zA-Z-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+))""")


def sanitize(text: str) -> str:
    """متن را به HTML امن برای تلگرام تبدیل می‌کند.

    نکته: مدل گاهی خودش متن را escape کرده و `&lt;` می‌فرستد. اگر دوباره
    escape کنیم، کاربر `&lt;` را روی صفحه می‌بیند. پس اول unescape می‌کنیم
    و بعد یک‌بار، درست escape می‌کنیم. این کار idempotent است.
    """
    if not text:
        return ""

    # محتوای <code>/<pre> کد است، نه markup؛ جدا نگهش می‌داریم تا
    # unescape کردن، مثال‌های کد را به تگ واقعی تبدیل نکند.
    protected, text = _extract_code_blocks(text)

    text = _sanitize_markup(text)

    return _restore_code_blocks(text, protected)


#: نویسه‌های خصوصی یونیکد که در متن واقعی ظاهر نمی‌شوند.
_SENTINEL_START = "\ue000"
_SENTINEL_END = "\ue001"
_CODE_RE = re.compile(r"<\s*(code|pre)\b[^>]*>.*?<\s*/\s*\1\s*>", re.DOTALL | re.IGNORECASE)


def _extract_code_blocks(text: str) -> tuple[list[str], str]:
    found: list[str] = []

    def replace(match: re.Match[str]) -> str:
        inner = match.group(0)
        opening = re.match(r"<\s*(?:code|pre)\b[^>]*>", inner, re.IGNORECASE)
        closing = re.search(r"<\s*/\s*(?:code|pre)\s*>$", inner, re.IGNORECASE)
        if not opening or not closing:
            return escape(inner)
        body = inner[opening.end() : closing.start()]
        safe = escape(unescape(body))
        found.append(f"{opening.group(0)}{safe}{closing.group(0)}")
        return f"{_SENTINEL_START}{len(found) - 1}{_SENTINEL_END}"

    return found, _CODE_RE.sub(replace, text)


def _restore_code_blocks(text: str, protected: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return protected[index] if 0 <= index < len(protected) else ""

    return re.sub(rf"{_SENTINEL_START}(\d+){_SENTINEL_END}", replace, text)


def _sanitize_markup(text: str) -> str:
    text = unescape(text)

    # اول بلوک‌های خطرناک را کامل حذف کن.
    for tag in DROP_WITH_CONTENT:
        text = re.sub(
            rf"<\s*{tag}\b.*?<\s*/\s*{tag}\s*>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    out: list[str] = []
    open_tags: list[str] = []
    pos = 0

    for match in _TAG_RE.finditer(text):
        # متن قبل از تگ باید escape شود.
        out.append(escape(text[pos : match.start()]))
        pos = match.end()

        closing_slash, name, attrs, self_closing = match.groups()
        name = name.lower()

        if name not in ALLOWED_TAGS:
            # تگ ناشناخته: به‌جای حذف، به‌صورت متن نمایش بده.
            out.append(escape(match.group(0)))
            continue

        if closing_slash:
            if open_tags and open_tags[-1] == name:
                open_tags.pop()
                out.append(f"</{name}>")
            # تگ بسته بدون باز: نادیده بگیر (وگرنه تلگرام خطا می‌دهد)
            continue

        clean_attrs = _clean_attrs(name, attrs)
        if self_closing:
            out.append(f"<{name}{clean_attrs}/>")
            continue

        out.append(f"<{name}{clean_attrs}>")
        # تگ‌های void در تلگرام معنا ندارند؛ همه را باز نگه می‌داریم.
        open_tags.append(name)

    out.append(escape(text[pos:]))

    # هر تگی که باز مانده را ببند تا تلگرام شکایت نکند.
    for name in reversed(open_tags):
        out.append(f"</{name}>")

    return _tidy("".join(out))


def _clean_attrs(tag: str, raw_attrs: str) -> str:
    if not raw_attrs:
        return ""
    allowed = set(_ALLOWED_ATTRS)
    if tag == "a":
        allowed = {"href"}
    if tag == "tg-emoji":
        allowed = {"emoji-id"}
    if tag in {"span", "blockquote"}:
        allowed = {"class"}

    pieces: list[str] = []
    for attr_match in _ATTR_RE.finditer(raw_attrs):
        key = attr_match.group(1).lower()
        value = attr_match.group(3) or attr_match.group(4) or attr_match.group(5) or ""
        if key not in allowed:
            continue
        if key == "href":
            if not _is_safe_url(value):
                continue
            value = value.replace('"', "%22")
        pieces.append(f' {key}="{value}"')
    return "".join(pieces)


def _is_safe_url(url: str) -> bool:
    return url.lower().startswith(("http://", "https://", "tg://"))


def _tidy(html_text: str) -> str:
    """فاصله‌های اضافی و خطوط خالی پشت‌سرهم را مرتب می‌کند."""
    html_text = re.sub(r"[ \t]+\n", "\n", html_text)
    html_text = re.sub(r"\n{3,}", "\n\n", html_text)
    return html_text.strip()


def strip_tags(html_text: str) -> str:
    """فقط متن خالص (برای شمارش کاراکتر و اثر انگشت)."""
    text = _TAG_RE.sub("", html_text or "")
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
