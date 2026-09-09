"""تست رندر پست به پیام تلگرام."""

from __future__ import annotations

import re

from bioai_channel.chunk import MAX_TEXT_CHARS, visible_len
from bioai_channel.content.formats import get_format
from bioai_channel.renderer import DraftPost, build_hashtags, normalize_title, render

_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*\s*[^>]*?/?>")


def make_draft(**overrides) -> DraftPost:
    base = dict(
        format_id="fact",
        title="عنوان نمونه",
        hook="یک قلاب جذاب",
        body=["پاراگراف اول.", "پاراگراف دوم با p < 0.05."],
        sources=[{"title": "مقاله", "url": "https://example.org/paper"}],
        hashtags=["بیوانفورماتیک", "AI"],
        buttons=[{"text": "مخزن", "url": "https://github.com/x/y"}],
        image_prompt="a glowing cell",
    )
    base.update(overrides)
    return DraftPost(**base)


def test_render_produces_at_least_one_part():
    rendered = render(make_draft(), get_format("fact"), "@TestChannel")
    assert len(rendered.parts) >= 1
    assert rendered.total_chars > 0


def test_title_is_bold_and_has_emoji():
    rendered = render(make_draft(), get_format("fact"), "")
    assert rendered.parts[0].text.startswith("⚡ <b>")


def test_special_characters_are_escaped():
    rendered = render(make_draft(), get_format("fact"), "")
    text = rendered.parts[0].text
    assert "< 0.05" not in text
    assert "&lt; 0.05" in text


def test_hashtags_rendered_and_prefixed():
    draft = make_draft()
    rendered = render(draft, get_format("fact"), "")
    text = rendered.parts[0].text
    assert "#بیوانفورماتیک" in text
    assert "#AI" in text
    assert "#" + "AI " not in text.replace("#AI", "")


def test_fixed_hashtag_of_format_is_included():
    rendered = render(make_draft(hashtags=[]), get_format("joke"), "")
    assert "#طنز_بیولوژی" in rendered.parts[0].text


def test_sources_become_links_and_buttons():
    rendered = render(make_draft(), get_format("fact"), "")
    last = rendered.parts[-1]
    assert 'href="https://example.org/paper"' in last.text
    assert last.keyboard
    urls = [b["url"] for row in last.keyboard for b in row]
    assert "https://github.com/x/y" in urls


def test_no_source_block_when_sources_empty():
    rendered = render(make_draft(sources=[]), get_format("fact"), "")
    assert "منابع" not in rendered.parts[-1].text


def test_every_part_under_telegram_limit():
    long_body = ["پاراگراف طولانی " + "کلمه " * 200 for _ in range(20)]
    rendered = render(make_draft(format_id="deepdive", body=long_body), get_format("deepdive"), "")
    for part in rendered.parts:
        assert visible_len(part.text) <= MAX_TEXT_CHARS


def test_parts_do_not_exceed_format_max():
    long_body = ["پاراگراف " + "کلمه " * 60 for _ in range(30)]
    fmt = get_format("fact")  # max_parts = 1
    rendered = render(make_draft(format_id="fact", body=long_body), fmt, "")
    assert len(rendered.parts) <= fmt.max_parts


def test_balanced_tags_in_every_part():
    long_body = [f"<b>پاراگراف {i}</b> " + "کلمه " * 120 for i in range(40)]
    rendered = render(make_draft(format_id="deepdive", body=long_body), get_format("deepdive"), "")
    for part in rendered.parts:
        opens = len(re.findall(r"<\s*[a-zA-Z]", part.text))
        closes = len(re.findall(r"<\s*/", part.text))
        assert opens == closes, (opens, closes)


def test_long_title_is_truncated():
    title = "ع " * 80
    out = normalize_title(title, "🧬")
    plain = re.sub(r"<[^>]+>", "", out)
    assert len(plain) <= 95
    assert plain.endswith("…")


def test_signature_appears_when_given():
    rendered = render(make_draft(), get_format("fact"), "@Bio_with_AI")
    assert "@Bio_with_AI" in rendered.parts[-1].text


def test_no_poll_keywords_anywhere():
    rendered = render(make_draft(), get_format("fact"), "")
    text = rendered.as_text().lower()
    for banned in ("poll", "نظرسنجی", "vote"):
        assert banned not in text


def test_code_snippet_wrapped_in_code_tag():
    rendered = render(make_draft(code_snippet="conda install -c bioconda salmon"), get_format("toolbox"), "")
    text = rendered.as_text()
    assert "<code>conda install -c bioconda salmon</code>" in text
    # محتوای کد نباید به متن معمولی تبدیل شود
    assert "&lt;code&gt;" not in text


def test_code_snippet_with_html_example_is_escaped_not_rendered():
    snippet = 'df.query("p < 0.05")  # <b>not a tag</b>'
    rendered = render(make_draft(code_snippet=snippet), get_format("toolbox"), "")
    text = rendered.as_text()
    assert "&lt; 0.05" in text
    assert "<b>not a tag</b>" not in text


def test_hashtag_deduplication():
    draft = make_draft(hashtags=["AI", "ai", "AI"])
    tags = build_hashtags(draft, get_format("fact"))
    assert tags.count("#AI") == 1
