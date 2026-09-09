"""کلاینت نازک و مقاوم برای Gemini.

مسئولیت‌ها:
  - ساخت کلاینت
  - retry با backoff نمایی روی ۴۲۹ / ۵۰۰ / ۵۰۳
  - fallback روی مدل‌های جایگزین وقتی مدلی در دسترس نبود
  - گزارش سهمیهٔ مصرف‌شده در لاگ
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

#: کدهای HTTP که ارزش تلاش مجدد دارند.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_MARKERS = (
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "unavailable",
    "internal error",
    "deadline exceeded",
)


class GeminiError(RuntimeError):
    pass


class GeminiUnavailable(GeminiError):
    """مدل در دسترس نبود (۴۰۴ یا invalid model)."""


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_retryable(exc: Exception) -> bool:
    status = _status_of(exc)
    if status in RETRYABLE_STATUS:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in RETRYABLE_MARKERS)


def _is_missing_model(exc: Exception) -> bool:
    status = _status_of(exc)
    if status == 404:
        return True
    message = str(exc).lower()
    return "models/ is not found" in message or "is not found for api version" in message or "invalid model" in message


class GeminiClient:
    """پیچی دور google.genai با retry و fallback."""

    def __init__(
        self,
        api_key: str,
        max_retries: int = 3,
        timeout: int = 180,
        client: Any | None = None,
    ) -> None:
        self.max_retries = max(1, max_retries)
        self.timeout = timeout
        if client is not None:
            self._client = client
        else:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=timeout * 1000),
            )

    # ------------------------------------------------------------------ API
    def generate(
        self,
        model: str,
        contents: Any,
        config: Any,
        fallback_models: tuple[str, ...] = (),
    ) -> Any:
        """یک فراخوانی generate_content با retry و fallback مدل."""
        models = (model, *fallback_models)
        last_error: Exception | None = None

        for index, candidate in enumerate(models):
            try:
                return self._generate_with_retry(candidate, contents, config)
            except GeminiUnavailable as exc:
                last_error = exc
                if index + 1 < len(models):
                    logger.warning(
                        "مدل %s در دسترس نبود (%s)؛ امتحان مدل %s",
                        candidate,
                        str(exc)[:120],
                        models[index + 1],
                    )
                    continue
                raise GeminiError(f"هیچ مدل متنی در دسترس نبود: {models}") from exc
            except GeminiError as exc:
                last_error = exc
                if index + 1 < len(models):
                    logger.warning("مدل %s شکست خورد؛ امتحان %s", candidate, models[index + 1])
                    continue
                raise

        raise GeminiError(f"فراخوانی Gemini ناموفق بود: {last_error}")

    def _generate_with_retry(self, model: str, contents: Any, config: Any) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as exc:  # noqa: BLE001 - SDK انواع خطای متنوعی پرتاب می‌کند
                if _is_missing_model(exc):
                    raise GeminiUnavailable(f"مدل {model} پیدا نشد: {exc}") from exc
                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise GeminiError(f"فراخوانی {model} شکست خورد: {exc}") from exc

                delay = min(30.0, (2 ** (attempt - 1)) * 2.0) + random.uniform(0, 1.5)
                logger.warning(
                    "تلاش %d/%d برای %s شکست خورد (%s). %.1f ثانیه صبر می‌کنیم…",
                    attempt,
                    self.max_retries,
                    model,
                    str(exc)[:140],
                    delay,
                )
                time.sleep(delay)


def usage_of(response: Any) -> str:
    """خلاصهٔ مصرف توکن برای لاگ."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return "usage=n/a"
    total = getattr(usage, "total_token_count", None)
    prompt = getattr(usage, "prompt_token_count", None)
    out = getattr(usage, "candidates_token_count", None)
    return f"usage total={total} in={prompt} out={out}"


def grounding_used(response: Any) -> bool:
    """آیا واقعاً از Grounding with Google Search استفاده شده؟"""
    metadata = getattr(response, "candidates", None)
    if not metadata:
        return False
    for candidate in metadata:
        grounding = getattr(candidate, "grounding_metadata", None)
        if grounding is None:
            continue
        if getattr(grounding, "grounding_chunks", None) or getattr(
            grounding, "web_search_queries", None
        ):
            return True
        if getattr(grounding, "search_entry_point", None):
            return True
    return False
