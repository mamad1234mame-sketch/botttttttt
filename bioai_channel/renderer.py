"""تبدیل ساختار پست به پیام‌های آمادهٔ تلگرام.

اینجا جایی است که «پست» به چیزهایی که تلگرام واقعاً می‌فهمد تبدیل می‌شود:
متن HTML امن، تکه‌های زیر ۴۰۹۶ کاراکتر، دکمه‌های inline و برچسب‌ها.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .chunk import split_message, visible_len
from .content.formats import PostFormat
from .tg_html import sanitize

MAX_HASHTAGS = 6
MAX_TITLE_CHARS = 90


@dataclass(slots=True)
class RenderedPart:
    text: str
    keyboard: list[list[dict[str, str]]] | None = None
    link_preview: bool = False
    silent: bool = False
    is_first: bool = False


@dataclass(slots=True)
class RenderedPost:
    parts: list[RenderedPart] = field(default_factory=list)
    total_chars: int = 0

    def as_text(self) -> str:
        return "\n\n--- part ---\n\n".join(p.text for p in self.parts)


@dataclass(slots=True)
class DraftPost:
    """ساختار خنثی یک پست (از JSON مدل ساخته می‌شود)."""

    format_id: str
    title: str
    hook: str = ""
    body: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    buttons: list[dict[str, str]] = field(default_factory=list)
    code_snippet: str = ""
    silent: bool = False
    topic_slug: str = ""
    image_prompt: str = ""


def _clean_hashtag(tag: str) -> str:
    tag = tag.strip().lstrip("#").strip()
    tag = re.sub(r"\s+", "_", tag)
    tag = re.sub(r"[^\w\u0600-\u06FF\-]", "", tag, flags=re.UNICODE)
    return tag


def build_hashtags(draft: DraftPost, fmt: PostFormat) -> str:
    tags: list[str] = []
    for tag in list(fmt.fixed_hashtags) + list(draft.hashtags):
        clean = _clean_hashtag(tag)
        if clean and clean not in tags:
            tags.append(clean)
    tags = tags[:MAX_HASHTAGS]
    return " ".join(f"#{t}" for t in tags)


def normalize_title(title: str, emoji: str) -> str:
    title = (title or "").strip()
    title = re.sub(r"\s+", " ", title)
    # اگر مدل خودش تیتر را بولد کرده، تگ را بردار تا دوتایی نشود.
    title = re.sub(r"^<\s*/?(b|strong|i|em)\s*>", "", title).strip()
    title = re.sub(r"<\s*/?(b|strong|i|em)\s*>$", "", title).strip()
    if len(title) > MAX_TITLE_CHARS:
        cut = title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0]
        title = cut.rstrip("،,.;: ") + "…"
    return f"{emoji} <b>{sanitize(title)}</b>" if emoji else f"<b>{sanitize(title)}</b>"


def source_lines(sources: list[dict[str, str]]) -> tuple[str, list[list[dict[str, str]]]]:
    """بخش منابع را به HTML و دکمه‌های inline تبدیل می‌کند."""
    if not sources:
        return "", []

    lines: list[str] = ["", "<b>منابع</b>"]
    buttons: list[list[dict[str, str]]] = []

    for index, source in enumerate(sources[:4], start=1):
        title = sanitize((source.get("title") or "").strip() or f"منبع {index}")
        url = (source.get("url") or "").strip()
        if url.startswith(("http://", "https://")):
            lines.append(f'{index}. <a href="{url}">{title}</a>')
            label = title.replace("<b>", "").replace("</b>", "")[:32] or f"منبع {index}"
            buttons.append([{"text": f"🔗 {label}", "url": url}])
        else:
            lines.append(f"{index}. {title}")

    return "\n".join(lines), buttons[:4]


def render(draft: DraftPost, fmt: PostFormat, signature: str = "") -> RenderedPost:
    """پیش‌نویس را به پیام(های) تلگرام تبدیل می‌کند."""
    blocks: list[str] = [normalize_title(draft.title, fmt.emoji)]

    if draft.hook.strip():
        blocks.append(f"<i>{sanitize(draft.hook.strip())}</i>")

    for paragraph in draft.body:
        paragraph = (paragraph or "").strip()
        if paragraph:
            blocks.append(sanitize(paragraph))

    if draft.code_snippet.strip():
        # فقط <code> می‌گذاریم؛ escape کردن محتوای کد کار sanitize است
        # (بلوک‌های code را دست‌نخورده و امن نگه می‌دارد).
        blocks.append(f"<code>{draft.code_snippet.strip()}</code>")

    source_block, source_buttons = source_lines(draft.sources)
    if source_block:
        blocks.append(source_block)

    tags = build_hashtags(draft, fmt)
    footer_parts = [tags, signature.strip()] if signature.strip() else [tags]
    footer = "\n".join(p for p in footer_parts if p)
    if footer:
        blocks.append(footer)

    text = "\n\n".join(b for b in blocks if b)

    # اگر قالب تک‌تکه است ولی متن طولانی شد، به چند رشته بشکن.
    parts_text = split_message(text)
    if len(parts_text) > fmt.max_parts:
        parts_text = _merge_overflow(parts_text, fmt.max_parts)

    buttons = draft_buttons(draft) + source_buttons

    rendered_parts: list[RenderedPart] = []
    for index, part_text in enumerate(parts_text):
        rendered_parts.append(
            RenderedPart(
                text=part_text,
                keyboard=buttons if index == len(parts_text) - 1 and buttons else None,
                link_preview=fmt.link_preview,
                silent=bool(draft.silent and fmt.silent_ok),
                is_first=index == 0,
            )
        )

    total = sum(visible_len(p.text) for p in rendered_parts)
    return RenderedPost(parts=rendered_parts, total_chars=total)


def draft_buttons(draft: DraftPost) -> list[list[dict[str, str]]]:
    out: list[list[dict[str, str]]] = []
    for button in draft.buttons[:3]:
        text = (button.get("text") or "").strip()[:40]
        url = (button.get("url") or "").strip()
        if text and url.startswith(("http://", "https://")):
            out.append([{"text": f"↗ {text}", "url": url}])
    return out


def _merge_overflow(parts: list[str], max_parts: int) -> list[str]:
    """اگر تکه‌ها بیشتر از سقف قالب شد، تا جای ممکن ادغام و در نهایت کوتاه کن.

    هرگز تکه‌ای نمی‌سازیم که از حد تلگرام بزرگ‌تر باشد.
    """
    from .chunk import SAFE_TEXT_CHARS, visible_len

    if len(parts) <= max_parts:
        return parts

    merged: list[str] = list(parts[:max_parts])
    for extra in parts[max_parts:]:
        candidate = merged[-1] + "\n\n" + extra
        if visible_len(candidate) <= SAFE_TEXT_CHARS:
            merged[-1] = candidate
        else:
            # جا نمی‌شود: با یک نشانگر ادامه، دم را حذف کن.
            marker = "\n\n<i>…ادامه در پست بعدی</i>"
            merged[-1] = merged[-1] + marker
            break
    return merged
