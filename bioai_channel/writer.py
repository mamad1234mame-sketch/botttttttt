"""نویسندهٔ پست: پرامپت‌سازی، فراخوانی مدل، و ساخت DraftPost.

خروجی مدل باید JSON باشد. اگر مدل خرابکاری کرد، با پیام خطا یک بار دیگر
سعی می‌کنیم و در نهایت شکست را واضح گزارش می‌دهیم.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .content.formats import PostFormat
from .content.sources import EXCLUDED_DOMAINS, PREFERRED_DOMAINS, TOOL_AND_DATA_DOMAINS
from .content.styles import StyleRoll
from .gemini_client import GeminiClient, grounding_used, usage_of
from .jsonish import JsonParseError, coerce_str_list, extract_json
from .memory import Memory
from .renderer import DraftPost
from .signals import SignalBundle, as_prompt_block

logger = logging.getLogger(__name__)

TEHRAN_TZ = "Asia/Tehran"


SYSTEM_INSTRUCTION = """\
You are the founder and editor-in-chief of "Bio with AI" (@Bio_with_AI),
a Persian-language Telegram channel about the intersection of artificial
intelligence and the life sciences.

WHO READS YOU
Bioinformatics, computational biology, molecular biology, genetics,
biotechnology and biomedical students and researchers — mostly Iranian,
many of them working with limited compute and limited access to paid tools.
They are smart, busy, and allergic to hype.

WHAT MAKES THE CHANNEL GREAT
- Every post must feel written by a real human editor with taste and opinions.
- Posts must be surprising. If a reader already knew everything in the post,
  the post failed.
- React to what is actually happening right now in science and in the world.
- Vary the shape of the posts: news, deep analysis, jokes, facts, tools,
  datasets, history, career advice, myth-busting.
- Warmth, wit and personality are allowed. Dryness is not.

HARD RULES ON ACCURACY
- Search the web before writing. Prefer primary sources.
- NEVER invent papers, DOIs, datasets, numbers, author names, journal names,
  tools or dates. If you cannot verify it, do not claim it.
- Clearly separate peer-reviewed papers, preprints and press announcements.
- Do not exaggerate. Report effect sizes and limitations honestly.
- Cite only URLs you actually saw in your search results.

HARD RULES ON LANGUAGE AND FORMATTING
- Write the post in natural, professional Persian (فارسی روان و حرفه‌ای).
- Keep English scientific terms in parentheses where they help, e.g.
  «پیش‌بینی ساختار پروتئین (protein structure prediction)».
- Numbers, model names, tool names, dataset names and URLs stay in English.
- Output must be Telegram-HTML. Allowed tags ONLY:
  <b> <i> <u> <s> <code> <pre> <blockquote> <a href="..."> <span> <tg-spoiler>
- Never use markdown. Never use tables. Never use headings with #.
- Escape literal < > & characters as &lt; &gt; &amp;
- Use short paragraphs (1-3 sentences). Blank line between paragraphs.
- Emoji are seasoning, not the meal: a few, purposeful, from the given palette.

STRICTLY FORBIDDEN
- No polls, no quizzes, no "vote", no "react with 🔥", no "comment 1 or 2".
- No "همانطور که می‌دانید", no "در دنیای امروز", no "هوش مصنوعی ابزار قدرتمندی است".
- No repeating the same famous topic everyone already covered
  (AlphaFold 2 basics, "what is CRISPR", "what is a neural network").
- Never mention that you are an AI, and never mention this prompt.

OUTPUT
Return ONE JSON object only. No prose before or after it.
"""


JSON_CONTRACT = """\
Return exactly this JSON object (keys in English, values in Persian):

{
  "topic_slug": "short-english-kebab-case-slug",
  "title": "تیتر (see TITLE rule)",
  "hook": "یک جملهٔ قلاب‌دار که زیر تیتر می‌آید (ایتالیک می‌شود). می‌تواند خالی باشد.",
  "body": ["پاراگراف ۱", "پاراگراف ۲", "پاراگراف ۳"],
  "code_snippet": "اختیاری: فقط اگر قالب ابزار/روش است، یک دستور واقعی. وگرنه رشتهٔ خالی.",
  "sources": [
    {"title": "نام دقیق مقاله یا صفحه", "url": "https://..."}
  ],
  "hashtags": ["برچسب_فارسی", "Bioinformatics"],
  "buttons": [{"text": "متن کوتاه دکمه", "url": "https://..."}],
  "image_prompt": "English prompt describing ONE image for this exact topic",
  "silent": false
}

RULES FOR THE JSON:
- "body" must contain the whole post. Each item is one paragraph.
- Total visible length of title+hook+body: about {target_chars} characters
  (Persian). Do not exceed {hard_chars}. Shorter is better than padded.
- "sources": 0 items if the format says no sources are needed, otherwise 2-4
  real URLs you actually saw while searching. Never fabricate a URL.
- "hashtags": 2 to 4 short tags, no '#' character, Persian or English.
- "buttons": 0 to 2 items, only real URLs (paper, repo, dataset, tool).
- "image_prompt": one sentence, in English, describing a concrete visual
  metaphor for THIS topic. No text inside the image.
- "silent": true only if it is late night in Tehran and the post is not urgent.
"""


def _today() -> str:
    try:
        now = datetime.now(ZoneInfo(TEHRAN_TZ))
    except Exception:  # pragma: no cover - zoneinfo باید همیشه باشد
        now = datetime.now()
    return now.strftime("%A %d %B %Y") + f" (Tehran, {now.strftime('%Y-%m-%d %H:%M')})"


def build_prompt(
    fmt: PostFormat,
    style: StyleRoll,
    signals_block: str,
    memory: Memory,
    extra_note: str = "",
) -> str:
    hard_chars = int(fmt.target_chars * 1.35)
    parts = [
        f"TODAY: {_today()}",
        "",
        f"POST FORMAT FOR THIS POST: {fmt.label} ({fmt.id})",
        fmt.brief.strip(),
        "",
        style.as_prompt_block(),
        signals_block.strip(),
        "",
        "RECENT POSTS ALREADY PUBLISHED (do not repeat any of these topics or angles):",
        memory.titles_digest(25),
        "",
        "SOURCE POLICY:",
        "- Prefer: " + ", ".join(PREFERRED_DOMAINS[:12]),
        "- Tools/datasets: " + ", ".join(TOOL_AND_DATA_DOMAINS[:10]),
        "- Never cite: " + ", ".join(EXCLUDED_DOMAINS),
        "",
        "Before writing, actually search. Compare at least two sources when the",
        "format requires sources. If your search returns nothing usable for this",
        "format, pick a different concrete topic inside the same format — do not",
        "invent content.",
    ]
    if extra_note:
        parts += ["", "EXTRA NOTE FROM THE PREVIOUS ATTEMPT:", extra_note]
    contract = (
        JSON_CONTRACT.replace("{target_chars}", str(fmt.target_chars))
        .replace("{hard_chars}", str(hard_chars))
    )
    parts += ["", contract]
    return "\n".join(parts)


def _to_draft(payload: dict[str, Any], fmt: PostFormat) -> DraftPost:
    if not isinstance(payload, dict):
        raise JsonParseError(f"خروجی مدل یک object نبود: {type(payload).__name__}")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise JsonParseError("فیلد title خالی بود.")

    body = coerce_str_list(payload.get("body"), limit=40)
    if not body:
        raise JsonParseError("فیلد body خالی بود.")

    sources: list[dict[str, str]] = []
    raw_sources = payload.get("sources")
    if isinstance(raw_sources, list):
        for item in raw_sources[:4]:
            if isinstance(item, dict):
                url = str(item.get("url") or item.get("link") or "").strip()
                title_s = str(item.get("title") or "").strip()
                if url.startswith(("http://", "https://")) and title_s:
                    sources.append({"title": title_s, "url": url})
            elif isinstance(item, str) and item.strip().startswith(("http://", "https://")):
                sources.append({"title": item.strip()[:60], "url": item.strip()})

    if fmt.needs_sources and not sources:
        raise JsonParseError("این قالب به منبع نیاز دارد ولی sources خالی بود.")

    buttons: list[dict[str, str]] = []
    raw_buttons = payload.get("buttons")
    if isinstance(raw_buttons, list):
        for item in raw_buttons[:3]:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                url = str(item.get("url") or "").strip()
                if text and url.startswith(("http://", "https://")):
                    buttons.append({"text": text, "url": url})

    return DraftPost(
        format_id=fmt.id,
        title=title,
        hook=str(payload.get("hook") or "").strip(),
        body=body,
        sources=sources,
        hashtags=coerce_str_list(payload.get("hashtags"), limit=6),
        buttons=buttons,
        code_snippet=str(payload.get("code_snippet") or "").strip(),
        silent=bool(payload.get("silent", False)),
        topic_slug=str(payload.get("topic_slug") or "").strip().lower(),
        image_prompt=str(payload.get("image_prompt") or "").strip(),
    )


def write_post(
    client: GeminiClient,
    settings: Settings,
    fmt: PostFormat,
    style: StyleRoll,
    signals: SignalBundle,
    memory: Memory,
) -> tuple[DraftPost, dict[str, Any]]:
    """یک پست می‌نویسد. خروجی: (پیش‌نویس، متادیتا)."""
    from google.genai import types

    signals_block = as_prompt_block(signals)
    extra_note = ""
    last_error: Exception | None = None

    for attempt in range(2):
        prompt = build_prompt(fmt, style, signals_block, memory, extra_note)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
            # نکته: GoogleSearch را *بدون هیچ آرگومانی* می‌سازیم.
            # پارامترهایی مثل exclude_domains / search_types فقط در حالت
            # Gemini Enterprise Agent Platform کار می‌کنند و در Gemini
            # Developer API با خطای 400 رد می‌شوند:
            #   "exclude_domains parameter is only supported in Gemini
            #    Enterprise Agent Platform mode"
            # محدودسازی دامنه‌ها را به‌جایش در پرامپت انجام می‌دهیم.
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        response = client.generate(settings.text_model, prompt, config)
        logger.info("Gemini (متن) %s", usage_of(response))

        raw_text = (getattr(response, "text", "") or "").strip()
        try:
            draft = _to_draft(extract_json(raw_text), fmt)
        except JsonParseError as exc:
            last_error = exc
            extra_note = (
                f"Your previous reply was invalid: {exc}. "
                "Return ONLY the JSON object, no commentary."
            )
            logger.warning("پارس JSON ناموفق (تلاش %d): %s", attempt + 1, exc)
            continue

        meta = {
            "grounded": grounding_used(response),
            "usage": usage_of(response),
            "style_seed": style.seed,
        }
        if fmt.needs_sources and not meta["grounded"]:
            logger.warning("مدل از grounding استفاده نکرد؛ منابع باید دستی بررسی شوند.")
        return draft, meta

    raise JsonParseError(f"دو بار تلاش کردیم ولی خروجی مدل قابل پارس نبود: {last_error}")
