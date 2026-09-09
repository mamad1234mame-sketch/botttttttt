"""لایهٔ ارسال به تلگرام.

نکات مهمی که اینجا رعایت شده:
  - تلگرام گاهی HTTP 200 می‌دهد ولی ok=false است؛ همیشه پاکت را چک می‌کنیم.
  - اگر parse_mode=HTML خطا داد، بدون parse_mode دوباره می‌فرستیم (fallback).
  - روی ۴۲۹ تلگرام، طبق retry_after صبر می‌کنیم.
  - تصویر با sendPhoto می‌رود و reply می‌شود به پیام اصلی.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from .chunk import MAX_TEXT_CHARS, visible_len

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
CAPTION_LIMIT = 1024
PHOTO_LIMIT_BYTES = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    pass


@dataclass(slots=True)
class TelegramClient:
    bot_token: str
    chat_id: str
    timeout: int = 30
    max_retries: int = 3
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({"User-Agent": "bioai-channel/1.0"})

    # ------------------------------------------------------------------ core
    def _call(self, method: str, payload: dict[str, Any], files: Any = None) -> dict[str, Any]:
        url = f"{TELEGRAM_API}/bot{self.bot_token}/{method}"
        attempt = 0
        while True:
            attempt += 1
            try:
                if files is not None:
                    response = self.session.post(url, data=payload, files=files, timeout=self.timeout)
                else:
                    response = self.session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise TelegramError(f"{method}: شبکه شکست خورد: {exc}") from exc
                time.sleep(2.0 * attempt)
                continue

            try:
                body = response.json()
            except ValueError:
                if attempt >= self.max_retries:
                    raise TelegramError(
                        f"{method}: پاسخ غیر JSON با HTTP {response.status_code}: {response.text[:200]}"
                    )
                time.sleep(2.0 * attempt)
                continue

            if body.get("ok"):
                return body.get("result", {})

            description = str(body.get("description", "unknown error"))
            error_code = int(body.get("error_code", response.status_code or 0))

            # محدودیت نرخ تلگرام
            if error_code == 429:
                retry_after = int(body.get("parameters", {}).get("retry_after", 3) or 3)
                if attempt >= self.max_retries:
                    raise TelegramError(f"{method}: 429 و تلاش‌ها تمام شد ({description})")
                logger.warning("تلگرام ۴۲۹ داد؛ %d ثانیه صبر می‌کنیم.", retry_after)
                time.sleep(retry_after + 1)
                continue

            # خطای سروری تلگرام
            if error_code >= 500 and attempt < self.max_retries:
                time.sleep(2.0 * attempt)
                continue

            raise TelegramError(f"{method} -> [{error_code}] {description}")

    # -------------------------------------------------------------- messages
    def send_message(
        self,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        link_preview: bool = False,
        silent: bool = False,
        reply_to_message_id: int | None = None,
    ) -> int:
        """یک پیام متنی می‌فرستد و message_id برمی‌گرداند."""
        if visible_len(text) > MAX_TEXT_CHARS:
            raise TelegramError(
                f"متن {visible_len(text)} کاراکتر است؛ از حد {MAX_TEXT_CHARS} بیشتر است."
            )

        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": json.dumps({"is_disabled": not link_preview}),
            "disable_notification": bool(silent),
        }
        if reply_to_message_id:
            payload["reply_parameters"] = json.dumps({"message_id": reply_to_message_id})
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            result = self._call("sendMessage", payload)
        except TelegramError as exc:
            if "parse entities" not in str(exc).lower() and "can't parse" not in str(exc).lower():
                raise
            logger.warning("HTML تلگرام پذیرفته نشد؛ بدون parse_mode می‌فرستیم. (%s)", exc)
            payload.pop("parse_mode", None)
            result = self._call("sendMessage", payload)

        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not message_id:
            raise TelegramError(f"sendMessage موفق بود ولی message_id نداشت: {result!r}")
        return int(message_id)

    def send_photo(
        self,
        photo_bytes: bytes,
        caption: str = "",
        mime_type: str = "image/png",
        reply_to_message_id: int | None = None,
        silent: bool = False,
    ) -> int:
        if len(photo_bytes) > PHOTO_LIMIT_BYTES:
            raise TelegramError(
                f"تصویر {len(photo_bytes)/1024/1024:.1f} مگابایت است؛ حد تلگرام ۱۰ مگابایت است."
            )

        caption = caption[:CAPTION_LIMIT]
        data: dict[str, Any] = {
            "chat_id": self.chat_id,
            "parse_mode": "HTML",
            "disable_notification": bool(silent),
        }
        if caption:
            data["caption"] = caption
        if reply_to_message_id:
            data["reply_parameters"] = json.dumps({"message_id": reply_to_message_id})

        files = {"photo": ("post.png", photo_bytes, mime_type)}
        try:
            result = self._call("sendPhoto", data, files=files)
        except TelegramError as exc:
            if "parse entities" not in str(exc).lower() and "can't parse" not in str(exc).lower():
                raise
            logger.warning("کپشن HTML پذیرفته نشد؛ بدون parse_mode می‌فرستیم.")
            data.pop("parse_mode", None)
            result = self._call("sendPhoto", data, files=files)

        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not message_id:
            raise TelegramError(f"sendPhoto موفق بود ولی message_id نداشت: {result!r}")
        return int(message_id)

    # ----------------------------------------------------------------- misc
    def me(self) -> dict[str, Any]:
        """اطلاعات بات — برای health check."""
        return self._call("getMe", {})

    def chat_info(self) -> dict[str, Any]:
        return self._call("getChat", {"chat_id": self.chat_id})
