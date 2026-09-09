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
    """یک تصویر تولید می‌کند؛ در صورت شکست None برمی‌گرداند."""
    from google.genai import types

    prompt = build_image_prompt(topic_prompt, style)
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=ASPECT_RATIO, output_mime_type="image/png"),
    )

    models = (settings.image_model, *settings.image_model_fallbacks)
    for index, model in enumerate(models):
        try:
            response = client.generate(model, prompt, config)
        except GeminiError as exc:
            logger.warning("تولید تصویر با %s شکست خورد: %s", model, str(exc)[:160])
            continue

        image = _extract_image(response)
        if image is not None:
            logger.info("تصویر ساخته شد با %s (%.0f KB) — %s", model, image.size_kb, usage_of(response))
            return image

        logger.warning("مدل %s تصویری برنگرداند.", model)
        if index + 1 >= len(models):
            break

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
