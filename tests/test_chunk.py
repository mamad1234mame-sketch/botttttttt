"""تست تکه‌کنندهٔ پیام تلگرام."""

from __future__ import annotations

import re

from bioai_channel.chunk import MAX_TEXT_CHARS, SAFE_TEXT_CHARS, split_message, visible_len
from bioai_channel.tg_html import sanitize

_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*\s*[^>]*?/?>")


def persian_paragraph(seed: int, words: int = 40) -> str:
    base = ["پژوهشگران", "در", "این", "مطالعه", "نشان", "دادند", "که", "مدل", "دقت", "بالایی", "دارد"]
    out = []
    for i in range(words):
        out.append(base[(seed + i) % len(base)])
    return " ".join(out) + f" ({seed})"


def test_short_text_is_one_part():
    text = sanitize("یک پیام کوتاه با <b>بولد</b>.")
    parts = split_message(text)
    assert len(parts) == 1
    assert parts[0] == text


def test_long_text_is_split_under_the_limit():
    long_text = "\n\n".join(persian_paragraph(i) for i in range(60))
    parts = split_message(long_text)

    assert len(parts) > 1
    for part in parts:
        assert visible_len(part) <= MAX_TEXT_CHARS, visible_len(part)


def test_no_part_exceeds_safe_limit():
    long_text = "\n\n".join(persian_paragraph(i, words=80) for i in range(40))
    for part in split_message(long_text):
        assert visible_len(part) <= SAFE_TEXT_CHARS


def test_html_tags_do_not_count_toward_limit():
    # تگ‌ها باید در محاسبهٔ طول دیده‌شده حساب نشوند.
    body = "کلمه " * 100
    text = sanitize(f"<b>{body}</b>")
    assert visible_len(text) == len(body)


def test_each_part_has_balanced_tags():
    long_text = "\n\n".join(
        f"<b>{persian_paragraph(i)}</b>\n\n<i>{persian_paragraph(i + 100)}</i>" for i in range(30)
    )
    parts = split_message(long_text)
    assert len(parts) > 1
    for part in parts:
        opens = len(_TAG_RE.findall(part))
        open_count = len(re.findall(r"<\s*[a-zA-Z]", part))
        close_count = len(re.findall(r"<\s*/", part))
        assert open_count == close_count, (open_count, close_count, opens)


def test_never_breaks_inside_a_url():
    url = "https://example.org/a-very-long-path/" + "x" * 120
    text = sanitize(("متن " * 900) + f"\n\nمنبع: {url}")
    parts = split_message(text)
    joined = "".join(parts)
    assert url in joined or url.split("/")[-1] in "".join(parts)
    for part in parts:
        # هیچ تکه‌ای نباید با یک «<» ناقص تمام شود
        assert not part.rstrip().endswith("<")


def test_empty_input_gives_no_parts():
    assert split_message("") == []
    assert split_message("   ") == []


def test_huge_single_paragraph_still_splits():
    huge = " ".join(["کلمه‌ای‌بسیاربلند"] * 1200)
    parts = split_message(sanitize(huge))
    assert len(parts) > 1
    for part in parts:
        assert visible_len(part) <= MAX_TEXT_CHARS


def test_realistic_post_size_is_single_part():
    post = "\n\n".join(persian_paragraph(i) for i in range(8))
    assert len(split_message(sanitize(post))) == 1
