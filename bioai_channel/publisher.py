"""ارکستراسیون کل جریان: سیگنال → انتخاب قالب → نوشتن → تصویر → ارسال.

این ماژول هیچ وابستگی مستقیمی به google.genai ندارد؛ کلاینت تزریق می‌شود.
پس کاملاً قابل تست است.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from . import image as image_module
from . import signals as signals_module
from . import writer as writer_module
from .chunk import SAFE_TEXT_CHARS, visible_len
from .config import Settings
from .content.styles import StyleRoll, roll_style
from .gemini_client import GeminiClient, GeminiError
from .memory import Memory, PostRecord, fingerprint, utcnow
from .planner import PlanDecision, pick_forced, weighted_choice
from .renderer import RenderedPost, render
from .telegram import TelegramClient, TelegramError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    ok: bool
    format_id: str = ""
    title: str = ""
    parts: int = 0
    chars: int = 0
    image: bool = False
    message_ids: list[int] = field(default_factory=list)
    grounded: bool = False
    error: str = ""
    plan_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "format": self.format_id,
            "title": self.title,
            "parts": self.parts,
            "chars": self.chars,
            "image": self.image,
            "grounded": self.grounded,
            "message_ids": self.message_ids,
            "plan_reason": self.plan_reason,
            "error": self.error,
        }


@dataclass(slots=True)
class Publisher:
    settings: Settings
    gemini: GeminiClient
    telegram: TelegramClient
    memory: Memory
    rng: random.Random | None = None

    def run(self, forced_format: str | None = None) -> RunResult:
        result = RunResult(ok=False)
        rng = self.rng or random.SystemRandom()

        # ۱) انتخاب قالب -------------------------------------------------
        decision: PlanDecision = (
            pick_forced(forced_format) if forced_format else weighted_choice(self.memory, rng)
        )
        fmt = decision.fmt
        result.format_id = fmt.id
        result.plan_reason = decision.reason
        logger.info("قالب انتخاب‌شده: %s (%s) — %s", fmt.id, fmt.label, decision.reason)

        # ۲) سیگنال‌ها ---------------------------------------------------
        if self.settings.skip_signals:
            bundle = signals_module.SignalBundle()
            logger.info("سیگنال‌ها رد شدند (SKIP_SIGNALS).")
        else:
            bundle = self._gather_signals()

        # ۳) نوشتن -------------------------------------------------------
        style: StyleRoll | None = None
        draft = None
        for attempt in range(3):
            style = roll_style(rng)
            try:
                draft, meta = writer_module.write_post(
                    self.gemini, self.settings, fmt, style, bundle, self.memory
                )
            except (GeminiError, ValueError) as exc:
                logger.warning("نوشتن پست شکست خورد (تلاش %d/3): %s", attempt + 1, exc)
                # سهمیهٔ روزانه تا ریست برنمی‌گردد؛ تلاش مجدد فقط سهمیهٔ
                # بقیهٔ مدل‌ها را هم می‌سوزاند. پس زودتر خارج شو.
                if "سهمیهٔ روزانه" in str(exc):
                    result.error = f"quota exhausted: {exc}"
                    return result
                if attempt == 2:
                    result.error = f"write failed: {exc}"
                    return result
                continue

            fp = fingerprint(draft.title, " ".join(draft.body))
            if self.memory.is_duplicate(fp):
                logger.warning("پست تکراری تشخیص داده شد؛ دوباره می‌نویسیم. (%s)", draft.title)
                if attempt == 2:
                    result.error = "duplicate content after 3 attempts"
                    return result
                continue

            result.title = draft.title
            result.grounded = bool(meta.get("grounded"))
            break

        if draft is None or style is None:
            result.error = "no draft produced"
            return result

        # ۴) رندر --------------------------------------------------------
        rendered = render(draft, fmt, self.settings.signature)
        if not rendered.parts:
            result.error = "rendered post was empty"
            return result
        try:
            self._guard_lengths(rendered)
        except TelegramError as exc:
            result.error = f"render: {exc}"
            return result
        result.parts = len(rendered.parts)
        result.chars = rendered.total_chars

        # ۵) تصویر -------------------------------------------------------
        generated = None
        if fmt.needs_image and not self.settings.skip_images and not self.settings.dry_run:
            # فاصلهٔ کوتاه بین پایان تولید متن و شروع تولید تصویر.
            image_delay = 3
            logger.info("متن آماده شد؛ %d ثانیه تا شروع تولید تصویر صبر می‌کنیم…", image_delay)
            time.sleep(image_delay)
            try:
                generated = image_module.generate(self.gemini, self.settings, draft.image_prompt, style)
            except Exception as exc:  # noqa: BLE001 - تصویر هیچ‌وقت نباید اجرا را بکشد
                logger.error("خطای غیرمنتظره در تولید تصویر: %s", exc)
        result.image = generated is not None

        # ۶) ارسال -------------------------------------------------------
        if self.settings.dry_run:
            logger.info("DRY RUN — پیام ارسال نشد:\n%s", rendered.as_text())
            result.ok = True
            result.message_ids = []
            self._remember(draft, fmt, rendered, None, generated is not None)
            return result

        try:
            result.message_ids = self._send(rendered, generated, draft)
        except TelegramError as exc:
            result.error = f"telegram: {exc}"
            logger.error("ارسال به تلگرام شکست خورد: %s", exc)
            return result

        result.ok = True
        self._remember(draft, fmt, rendered, result.message_ids[0] if result.message_ids else None,
                       generated is not None)
        logger.info(
            "منتشر شد: [%s] %s (%d تکه، %d کاراکتر، تصویر=%s)",
            fmt.id,
            draft.title,
            result.parts,
            result.chars,
            result.image,
        )
        return result

    # ------------------------------------------------------------- helpers
    def _gather_signals(self) -> signals_module.SignalBundle:
        try:
            return signals_module.gather(
                regions=self.settings.trends_regions,
                max_items=self.settings.signal_max_items,
                timeout=self.settings.signal_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("گرفتن سیگنال‌ها شکست خورد؛ بدون سیگنال ادامه می‌دهیم: %s", exc)
            bundle = signals_module.SignalBundle()
            bundle.errors.append(str(exc))
            return bundle

    def _send(
        self,
        rendered: RenderedPost,
        generated: image_module.GeneratedImage | None,
        draft: Any,
    ) -> list[int]:
        message_ids: list[int] = []
        anchor: int | None = None

        for index, part in enumerate(rendered.parts):
            markup = (
                {"inline_keyboard": part.keyboard} if part.keyboard else None
            )
            message_id = self.telegram.send_message(
                text=part.text,
                reply_markup=markup,
                link_preview=part.link_preview and index == 0,
                silent=part.silent,
                reply_to_message_id=anchor if index > 0 else None,
            )
            message_ids.append(message_id)
            if anchor is None:
                anchor = message_id

        if generated is not None:
            caption = self._image_caption(draft, rendered)
            photo_id = self.telegram.send_photo(
                photo_bytes=generated.data,
                caption=caption,
                mime_type=generated.mime_type,
                reply_to_message_id=anchor,
                silent=bool(rendered.parts[0].silent),
            )
            message_ids.append(photo_id)

        return message_ids

    @staticmethod
    def _image_caption(draft: Any, rendered: RenderedPost) -> str:
        from .tg_html import sanitize

        title = sanitize(draft.title)
        caption = f"<b>{title}</b>"
        if len(caption) > 900:
            caption = caption[:900] + "…</b>"
        return caption

    @staticmethod
    def _guard_lengths(rendered: RenderedPost) -> None:
        for index, part in enumerate(rendered.parts):
            length = visible_len(part.text)
            if length > SAFE_TEXT_CHARS:
                raise TelegramError(
                    f"تکهٔ {index + 1} هنوز {length} کاراکتر است (سقف {SAFE_TEXT_CHARS})."
                )

    def _remember(
        self,
        draft: Any,
        fmt: Any,
        rendered: RenderedPost,
        message_id: int | None,
        image_used: bool,
    ) -> None:
        record = PostRecord(
            ts=utcnow().isoformat(),
            format=fmt.id,
            title=draft.title,
            topic_slug=draft.topic_slug,
            fingerprint=fingerprint(draft.title, " ".join(draft.body)),
            message_id=message_id,
            image_used=image_used,
            chars=rendered.total_chars,
        )
        self.memory.add(record)
        self.memory.save()
