"""کتابخانهٔ «سبک» — چیزی که باعث می‌شود دو پست پشت‌سرهم شبیه هم نباشند.

هر اجرا یک StyleRoll می‌گیرد که ترکیبی تصادفی (ولی کنترل‌شده) از:
  سبک بازشدن پست، خانوادهٔ ایموجی، سبک تیتر، نوع پایان‌بندی و سبک تصویر.

این ترکیب به‌صورت متن به مدل داده می‌شود. نتیجه: تنوع واقعی، نه
تنوع ظاهری.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


OPENINGS: tuple[str, ...] = (
    "با یک عدد شروع کن که مخاطب انتظارش را ندارد.",
    "با یک پرسش تند و کوتاه شروع کن که مستقیم ذهن را درگیر کند.",
    "با یک صحنهٔ کوتاه از آزمایشگاه یا از دل داده‌ها شروع کن.",
    "با یک تناقض ظاهری شروع کن: چیزی که به نظر می‌رسد نباید کار کند ولی کار می‌کند.",
    "با یک جملهٔ خبری کوتاه و محکم شروع کن. بدون مقدمه‌چینی.",
    "با یک مقایسهٔ غیرمنتظره شروع کن (مثلاً یک مفهوم زیستی با یک چیز روزمره).",
    "با نقل یک جملهٔ کوتاه از مقاله یا از نویسنده‌اش شروع کن.",
    "با یک اعتراف صادقانه شروع کن: «سال‌ها فکر می‌کردیم…»",
    "با یک تصویر ذهنی شروع کن که خواننده بتواند ببیندش.",
    "با یک «اشتباه رایج» شروع کن و بعد درستش را بگو.",
    "بدون هیچ مقدمه‌ای مستقیم برو سر اصل مطلب.",
    "با یک تاریخ یا یک رکورد شروع کن.",
)

TITLE_STYLES: tuple[str, ...] = (
    "تیتر خبری کوتاه و کوبنده (حداکثر ۸ کلمه).",
    "تیتر پرسشی که واقعاً سؤال ایجاد کند.",
    "تیتری که یک عدد یا یک نتیجهٔ مشخص در خودش داشته باشد.",
    "تیتر دو بخشی با دونقطه: «موضوع: نکتهٔ اصلی».",
    "تیتری که ادعا کند و خواننده بخواهد دلیلش را بداند.",
    "تیتر بدون فعل، فقط تصویر ذهنی.",
    "تیتری با یک اصطلاح تخصصی انگلیسی که برای مخاطب آشناست.",
)

EMOJI_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("🧬", "🔬", "🧪", "⚗️"),
    ("🧠", "🤖", "📊", "📈"),
    ("🦠", "🔎", "🧫", "🩸"),
    ("🧩", "🗂️", "🧮", "⚙️"),
    ("🌡️", "🩻", "💊", "🧷"),
    ("🦋", "🌿", "🐚", "🕸️"),
    ("⚡", "🚀", "🛰️", "🧲"),
)

ENDING_STYLES: tuple[str, ...] = (
    "با یک پرسش تیز تمام کن که واقعاً جای فکر داشته باشد.",
    "با یک جملهٔ کوتاه جمع‌بندی تمام کن؛ بدون پرسش.",
    "با دعوت از مخاطب برای فرستادن تجربهٔ شخصی‌اش تمام کن.",
    "با یک پیش‌بینی جسورانه (و صادقانه برچسب‌خورده) تمام کن.",
    "با یک نکتهٔ عملی «همین امروز این را امتحان کن» تمام کن.",
    "با اشاره به چیزی که فردا منتشر می‌شود تمام کن (کنجکاوی).",
    "با یک ارجاع به بحث داغ این حوزه تمام کن.",
    "بدون هیچ پایان‌بندی اضافه؛ آخرین پاراگراف همان پایان باشد.",
    "با یک هشدار کوتاه دربارهٔ سوءبرداشت رایج تمام کن.",
)

IMAGE_STYLES: tuple[str, ...] = (
    "detailed scientific illustration, editorial style, clean vector shapes, "
    "muted teal and coral palette, white background, high detail",
    "isometric 3D render, soft studio lighting, glass and matte materials, "
    "pastel scientific palette, subtle depth of field",
    "vintage 19th-century biology textbook engraving, fine ink hatching, "
    "aged cream paper, hand-annotated labels in English",
    "photorealistic cryo-EM / electron microscopy aesthetic, monochrome blue-grey, "
    "dramatic scale, ultra fine detail",
    "fluorescence microscopy aesthetic, dark background, glowing cyan and magenta "
    "structures, shallow depth of field",
    "minimalist data-visualization poster, geometric abstraction of the concept, "
    "strong typographic grid, limited palette of three colors",
    "conceptual editorial photography, macro lens, laboratory objects rearranged "
    "into a metaphor, natural light",
    "hand-drawn ink and watercolor scientific sketch, visible pencil lines, "
    "loose composition, notebook margins",
    "retro-futuristic laboratory scene, 1970s color grading, analog instruments "
    "mixed with biological samples",
    "paper-cut collage style, layered shadows, bold shapes, "
    "science-magazine cover composition",
)

IMAGE_MOODS: tuple[str, ...] = (
    "wonder and discovery",
    "clinical precision",
    "playful curiosity",
    "quiet intensity",
    "scale and awe",
    "warm and human",
)


@dataclass(frozen=True, slots=True)
class StyleRoll:
    """یک ترکیب سبکی برای یک پست."""

    opening: str
    title_style: str
    emoji_family: tuple[str, ...]
    ending_style: str
    image_style: str
    image_mood: str
    #: یک seed عددی که اگر لازم شد همان سبک را دوباره بسازیم.
    seed: int

    def as_prompt_block(self) -> str:
        emojis = " ".join(self.emoji_family)
        return (
            "STYLE BRIEF FOR THIS POST (must be respected):\n"
            f"- OPENING: {self.opening}\n"
            f"- TITLE: {self.title_style}\n"
            f"- EMOJI PALETTE (only from this set, 1-3 uses total): {emojis}\n"
            f"- ENDING: {self.ending_style}\n"
            "- Absolutely no polls, no quizzes, no 'vote now', no 'comment 1 or 2'.\n"
            "- Do not start with 'در دنیای...', 'امروزه...', 'همانطور که می‌دانید...'.\n"
            "- Never write the words: هوش مصنوعی به عنوان یک ابزار قدرتمند.\n"
        )

    def as_image_prompt_block(self) -> str:
        return (
            f"VISUAL STYLE: {self.image_style}\n"
            f"MOOD: {self.image_mood}\n"
            "- Absolutely no text, no letters, no numbers, no watermark, no logo in the image.\n"
            "- Composition must read as an editorial science-channel cover.\n"
        )


def roll_style(rng: random.Random | None = None) -> StyleRoll:
    """یک ترکیب سبکی تازه می‌سازد."""
    rng = rng or random.SystemRandom()
    seed = rng.randrange(1_000_000_000)
    inner = random.Random(seed)
    return StyleRoll(
        opening=inner.choice(OPENINGS),
        title_style=inner.choice(TITLE_STYLES),
        emoji_family=inner.choice(EMOJI_FAMILIES),
        ending_style=inner.choice(ENDING_STYLES),
        image_style=inner.choice(IMAGE_STYLES),
        image_mood=inner.choice(IMAGE_MOODS),
        seed=seed,
    )
