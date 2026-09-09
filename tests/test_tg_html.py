"""تست سانیتایزر HTML تلگرام."""

from __future__ import annotations

import pytest

from bioai_channel.tg_html import sanitize, strip_tags


def test_escapes_stray_angle_brackets_in_persian_science_text():
    out = sanitize("مقدار p < 0.05 معنادار بود و R² = 0.87 گزارش شد.")
    assert "&lt;" in out
    assert "< 0.05" not in out


def test_escapes_ampersand():
    out = sanitize("شرکت X & Y اعلام کرد")
    assert "&amp;" in out
    assert " & " not in out


def test_keeps_allowed_tags():
    out = sanitize("<b>تیتر</b> و <i>ایتالیک</i> و <code>کد</code>")
    assert "<b>تیتر</b>" in out
    assert "<i>ایتالیک</i>" in out
    assert "<code>کد</code>" in out


def test_drops_unknown_tags_but_keeps_their_text():
    out = sanitize("<h1>عنوان</h1>")
    assert "<h1>" not in out
    assert "عنوان" in out


def test_drops_script_blocks_entirely():
    out = sanitize("سلام <script>alert(1)</script> دنیا")
    assert "alert" not in out
    assert "script" not in out


def test_closes_unclosed_tags():
    out = sanitize("<b>باز مانده")
    assert out.count("<b>") == 1
    assert out.count("</b>") == 1


def test_strips_dangerous_attributes():
    out = sanitize('<a href="https://x.test" onclick="evil()">لینک</a>')
    assert "onclick" not in out
    assert 'href="https://x.test"' in out


def test_rejects_javascript_urls():
    out = sanitize('<a href="javascript:alert(1)">لینک</a>')
    assert "javascript:" not in out


def test_ignores_stray_closing_tag():
    out = sanitize("متن </b> بدون باز")
    assert "</b>" not in out


def test_keeps_tg_spoiler():
    out = sanitize("<tg-spoiler>اسپویل</tg-spoiler>")
    assert "<tg-spoiler>" in out
    assert "</tg-spoiler>" in out


def test_strips_tags_returns_plain_text():
    assert strip_tags("<b>سلام</b> <a href=\"https://x\">دنیا</a>") == "سلام دنیا"


def test_empty_input():
    assert sanitize("") == ""


@pytest.mark.parametrize(
    "raw",
    [
        "p < 0.05",
        "a > b",
        "5nM < IC50",
        "A & B",
        "<b>bold</b> و p < 0.01",
        "nested <b><i>deep</i></b> text",
    ],
)
def test_output_never_has_unbalanced_or_raw_specials(raw):
    out = sanitize(raw)
    # بعد از sanitize، هیچ '<' خامی جز تگ‌های مجاز نباید بماند.
    import re

    leftovers = [m.group(0) for m in re.finditer(r"<[^>]*>", out)]
    allowed = {"<b>", "</b>", "<i>", "</i>", "<code>", "</code>", "<u>", "</u>", "<s>", "</s>"}
    assert all(tag in allowed for tag in leftovers), leftovers
