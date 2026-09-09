"""تولید تصویر با Gemini (Nano Banana).

اگر تولید تصویر به هر دلیلی شکست خورد، کل اجرا نمی‌میرد؛ پست بدون تصویر
می‌رود و خطا لاگ می‌شود.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Settings
from .content.styles import StyleRoll
from .gemini_client import GeminiClient, GeminiError, usage_of

logger = logging.getLogger(__name__)

#: نسبت تصویر مناسب فید تلگرام.
ASPECT_RATIO = "1:1"

MAX_PROMPT_CHARS = 900


@dataclass(slots=True)
class GeneratedImage:
    data: bytes
    mime_type: str = "image/png"

    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024.0


def build_image_prompt(topic_prompt: str, style: StyleRoll) -> str:
    """پرامپت تصویر را از پرامپت مدل + سبک بصری این اجرا می‌سازد."""
    topic = (topic_prompt or "").strip()
    if not topic:
        topic = "an abstract scientific concept at the intersection of AI and biology"
    if len(topic) > MAX_PROMPT_CHARS:
        topic = topic[:MAX_PROMPT_CHARS]

    return (
        "Create a single original editorial illustration for a science channel post.\n"
        f"SUBJECT: {topic}\n"
        + style.as_image_prompt_block()
    )


def generate(
    client: GeminiClient,
    settings: Settings,
    topic_prompt: str,
    style: StyleRoll,
) -> GeneratedImage | None:
    """یک تصویر تولید می‌کند؛ در صورت شکست None برمی‌گرداند.

    مسیر تصویر دقیقاً مثل مسیر متن است: نردبان کامل مدل‌ها به کلاینت داده
    می‌شود تا سهمیهٔ روزانه که تمام شد *درجا* و بدون صبر به مدل بعدی برود
    و مدل‌های روی‌اکانت‌نبوده و سهمیه‌تمام‌شده را اصلاً صدا نزند.
    """
    from google.genai import types

    prompt = build_image_prompt(topic_prompt, style)
    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO, output_mime_type="image/png"),
    )

    ladder = settings.image_model_ladder
    #: مدل‌هایی که جواب دادند ولی تصویری برنگرداندند (این سهمیه نیست،
    #: پس ارزش یک بار امتحان دوباره را دارند).
    no_image: list[str] = []

    for index, model in enumerate(ladder):
        remaining = ladder[index + 1 :]
        # مدل‌هایی که قبلاً تصویر ندادند را به انتهای صف برگردان، ولی
        # هرگز مدلی را که همین حالا امتحان شد دوباره صدا نزن.
        fallbacks = tuple(m for m in (*remaining, *no_image) if m != model)

        try:
            response = client.generate(
                model, prompt, config, fallback_models=fallbacks
            )
        except GeminiError as exc:
            # خودِ کلاینت همهٔ مدل‌های زنده را امتحان کرده و باز هم نشده؛
            # ادامهٔ حلقه فایده ندارد چون همان مدل‌ها را دوباره صدا می‌زند.
            logger.warning("تولید تصویر ممکن نشد: %s", str(exc)[:200])
            break

        used = getattr(response, "model_used", None) or model
        image = _extract_image(response)
        if image is not None:
            logger.info(
                "تصویر ساخته شد با %s (%.0f KB) — %s",
                used,
                image.size_kb,
                usage_of(response),
            )
            return image

        logger.warning("مدل %s جواب داد ولی تصویری برنگرداند.", used)
        no_image.append(used)

    logger.error("تولید تصویر با هیچ مدلی ممکن نشد؛ پست بدون تصویر می‌رود.")
    return None


def _extract_image(response) -> GeneratedImage | None:
    """اولین تصویر را از پاسخ Gemini بیرون می‌کشد."""
    parts = getattr(response, "parts", None)
    if parts is None:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is not None and getattr(content, "parts", None):
                parts = content.parts
                break
    if not parts:
        return None

    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        data = getattr(inline, "data", None)
        if isinstance(data, str):
            import base64

            try:
                data = base64.b64decode(data)
            except ValueError:
                continue
        if isinstance(data, (bytes, bytearray)) and data:
            mime = getattr(inline, "mime_type", None) or "image/png"
            return GeneratedImage(data=bytes(data), mime_type=str(mime))
    return None
