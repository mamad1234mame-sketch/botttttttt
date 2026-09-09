"""تکه‌کردن متن برای تلگرام.

نکته‌ای که اکثر پیاده‌سازی‌ها اشتباه می‌کنند: حد ۴۰۹۶ کاراکتر تلگرام
**بعد از parse شدن entityها** حساب می‌شود. یعنی تگ‌های `<b>` و `<a href>`
حساب نمی‌شوند، ولی متن دیده‌شده حساب می‌شود.

پس:
  ۱) طول را روی متن دیده‌شده (strip tags) اندازه می‌گیریم.
  ۲) هیچ‌وقت وسط یک تگ یا وسط یک entity نمی‌بریم.
  ۳) تگ‌های باز را در تکهٔ بعدی دوباره باز می‌کنیم تا parse نشکند.
"""

from __future__ import annotations

import re

from .tg_html import sanitize, strip_tags

#: حد رسمی تلگرام ۴۰۹۶ است؛ ما حاشیهٔ امنیت می‌گذاریم.
MAX_TEXT_CHARS = 4096
SAFE_TEXT_CHARS = 3900

_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9-]*)\s*([^>]*?)\s*(/?)\s*>")
_URL_RE = re.compile(r"https?://\S+")


def visible_len(html_text: str) -> int:
    """طول متن دیده‌شده (همان چیزی که تلگرام می‌شمارد)."""
    return len(strip_tags(html_text))


def split_message(html_text: str, limit: int = SAFE_TEXT_CHARS) -> list[str]:
    """متن را به تکه‌هایی می‌شکند که هر کدام زیر limit کاراکتر دیده‌شده باشند."""
    text = sanitize(html_text)
    if visible_len(text) <= limit:
        return [text] if text else []

    units = _to_units(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    open_stack: list[str] = []

    def flush() -> None:
        nonlocal current, current_len, open_stack
        if not current:
            return
        body = "".join(current).strip("\n")
        if body:
            # تگ‌های باز را ببند، و برای تکهٔ بعدی یادداشت کن.
            chunks.append(body + "".join(f"</{t}>" for t in reversed(open_stack)))
        current = []
        current_len = 0
        if open_stack:
            reopen = "".join(t for t in open_stack)
            current.append(reopen)
            current_len = visible_len(reopen)

    for unit in units:
        unit_len = visible_len(unit)

        if unit_len > limit:
            # واحد خیلی بزرگ (مثلاً یک پاراگراف عظیم) → سخت بشکن.
            for piece in _hard_split(unit, limit):
                if current_len + visible_len(piece) > limit:
                    flush()
                current.append(piece)
                current_len += visible_len(piece)
                _sync_stack(piece, open_stack)
            continue

        if current_len + unit_len > limit:
            flush()

        current.append(unit)
        current_len += unit_len
        _sync_stack(unit, open_stack)

    flush()

    # تکه‌های خالی یا فقط-تگ را دور بریز.
    return [c for c in (c.strip() for c in chunks) if visible_len(c) > 0]


def _to_units(text: str) -> list[str]:
    """متن را به واحدهای شکستنی تبدیل می‌کند: پاراگراف → خط → جمله → کلمه."""
    paragraphs = re.split(r"(\n{2,})", text)
    units: list[str] = []
    for para in paragraphs:
        if not para:
            continue
        if para.strip() == "":
            units.append(para)
            continue
        for line in re.split(r"(\n)", para):
            if not line:
                continue
            if line == "\n":
                units.append(line)
                continue
            if visible_len(line) <= SAFE_TEXT_CHARS:
                units.append(line)
            else:
                units.extend(_split_long_line(line))
    return units


def _split_long_line(line: str) -> list[str]:
    """یک خط بلند را بر اساس جمله، و در نهایت کلمه می‌شکند."""
    pieces: list[str] = []
    buffer = ""
    for sentence in re.split(r"(?<=[.!?؟؛;:])\s+", line):
        if visible_len(buffer + sentence) <= SAFE_TEXT_CHARS:
            buffer += sentence + " "
        else:
            if buffer.strip():
                pieces.append(buffer)
            buffer = sentence + " "
    if buffer.strip():
        pieces.append(buffer)

    out: list[str] = []
    for piece in pieces:
        if visible_len(piece) <= SAFE_TEXT_CHARS:
            out.append(piece)
        else:
            words: list[str] = []
            for word in re.split(r"(\s+)", piece):
                if visible_len("".join(words) + word) <= SAFE_TEXT_CHARS:
                    words.append(word)
                else:
                    out.append("".join(words))
                    words = [word]
            if words:
                out.append("".join(words))
    return out


def _hard_split(text: str, limit: int) -> list[str]:
    """آخرین چاره: شکستن بدون توجه به مرز معنایی، ولی بدون شکستن تگ."""
    pieces: list[str] = []
    buffer = ""
    i = 0
    while i < len(text):
        match = _TAG_RE.match(text, i)
        if match:
            buffer += match.group(0)
            i = match.end()
            continue
        ch = text[i]
        if visible_len(buffer) + 1 > limit:
            pieces.append(buffer)
            buffer = ""
        buffer += ch
        i += 1
    if buffer:
        pieces.append(buffer)
    return pieces


def _sync_stack(unit: str, stack: list[str]) -> None:
    """وضعیت تگ‌های باز را بعد از افزودن یک واحد به‌روز می‌کند."""
    for match in _TAG_RE.finditer(unit):
        closing, name, _attrs, self_closing = match.groups()
        name = name.lower()
        if self_closing:
            continue
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                while stack and stack.pop() != name:
                    pass
        else:
            stack.append(name)
