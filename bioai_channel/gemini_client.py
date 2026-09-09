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
import re
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

#: نشانه‌های محدودیت *دقیقه‌ای* (RPM/TPM) — با چند ثانیه صبر حل می‌شود.
PER_MINUTE_MARKERS = (
    "per minute",
    "requests per min",
    "tokens per minute",
    "tokens per min",
    "_rpm",
    "_tpm",
)

#: نشانه‌های تمام شدن سهمیهٔ *روزانه* (RPD) — تا ریست (نیمه‌شب PT) برنمی‌گردد،
#: پس صبر کردن روی همان مدل فقط وقت هدر دادن است و باید *درجا* سراغ مدل
#: بعدی رفت.
DAILY_QUOTA_MARKERS = (
    "exceeded your current quota",
    "requests per day",
    "per day",
    "daily limit",
    "free daily limit",
    "quota will reset",
    "_rpd",
)

#: «limit: 0» یعنی سهمیهٔ این مدل روی این اکانت صفر است؛ باز هم روزانه است.
ZERO_QUOTA_RE = re.compile(r"\blimit:?\s*0\b", re.IGNORECASE)


class GeminiError(RuntimeError):
    pass


class GeminiUnavailable(GeminiError):
    """مدل در دسترس نبود (۴۰۴ یا invalid model)."""


class GeminiQuotaExhausted(GeminiError):
    """سهمیهٔ روزانهٔ مدل تمام شده؛ تا ریست (نیمه‌شب PT) برگشت ندارد."""


class GeminiNoModelsAvailable(GeminiError):
    """هیچ مدل قابل استفاده‌ای روی این اکانت پیدا نشد."""


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


def is_quota_error(exc: Exception) -> bool:
    """آیا خطا مربوط به تمام شدن سهمیه است؟"""
    message = str(exc).lower()
    return "resource_exhausted" in message or "exceeded your current quota" in message


def is_daily_quota_exhausted(exc: Exception) -> bool:
    """آیا سهمیهٔ *روزانه* تمام شده (نه محدودیت دقیقه‌ای)؟

    سهمیهٔ روزانه نیمه‌شب به وقت اقیانوس آرام ریست می‌شود؛ پس صبر کردنِ
    چند ثانیه‌ای فایده‌ای ندارد و باید *بلافاصله* سراغ مدل بعدی رفت.

    نکته: پیام‌های گوگل هر دو حالت را با RESOURCE_EXHAUSTED می‌فرستند و
    تنها تفاوتشان در متن است. اول حالت دقیقه‌ای را بررسی می‌کنیم تا یک
    محدودیت RPM را اشتباهاً «تمام شده» تشخیص ندهیم.
    """
    message = str(exc).lower()
    if any(marker in message for marker in PER_MINUTE_MARKERS):
        return False
    if any(marker in message for marker in DAILY_QUOTA_MARKERS):
        return True
    return bool(ZERO_QUOTA_RE.search(message))


def _is_missing_model(exc: Exception) -> bool:
    status = _status_of(exc)
    if status == 404:
        return True
    message = str(exc).lower()
    return "models/ is not found" in message or "is not found for api version" in message or "invalid model" in message


def _remember_model(response: Any, model: str) -> None:
    """اسم مدلی که واقعاً جواب داد را روی پاسخ می‌گذارد (بی‌صدا)."""
    try:
        object.__setattr__(response, "model_used", model)
    except Exception:  # noqa: BLE001 - پاسخ‌های slots‌دار یا فریز شده
        try:
            setattr(response, "model_used", model)
        except Exception:  # noqa: BLE001
            pass


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
        #: کش فهرست مدل‌های موجود روی اکانت (یک‌بار گرفته می‌شود).
        self._model_cache: set[str] | None = None
        #: مدل‌هایی که در *همین اجرا* سهمیهٔ روزانه‌شان تمام شده. تا ریست
        #: سهمیه فایده‌ای ندارد که دوباره امتحانشان کنیم؛ این‌جا ذخیره
        #: می‌شود تا بقیهٔ فراخوانی‌ها (متن، تصویر، …) درجا ردشان کنند.
        self._exhausted: set[str] = set()
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
    def list_models(self) -> set[str] | None:
        """اسم مدل‌هایی که روی این اکانت واقعاً وجود دارند.

        اگر گرفتن فهرست ممکن نشد، None برمی‌گردانیم تا سخت‌گیری نکنیم
        (بهتر است یک ۴۰۴ بخوریم تا اینکه بی‌دلیل چیزی را رد کنیم).
        """
        if self._model_cache is not None:
            return self._model_cache

        names: set[str] = set()
        try:
            for page in self._client.models.list():
                name = str(getattr(page, "name", "") or "")
                if name:
                    names.add(name.replace("models/", ""))
        except Exception as exc:  # noqa: BLE001
            logger.debug("گرفتن فهرست مدل‌ها ممکن نشد: %s", exc)
            self._model_cache = None
            return None

        self._model_cache = names or None
        if names:
            logger.info("%d مدل روی این اکانت در دسترس است.", len(names))
        return self._model_cache

    def exhausted_models(self) -> frozenset[str]:
        """مدل‌هایی که در این اجرا سهمیهٔ روزانه‌شان تمام شده."""
        return frozenset(self._exhausted)

    def generate(
        self,
        model: str,
        contents: Any,
        config: Any,
        fallback_models: tuple[str, ...] = (),
    ) -> Any:
        """یک فراخوانی generate_content با retry و fallback مدل.

        ترتیب حذف مدل‌ها (همه قبل از اولین درخواست شبکه انجام می‌شود):
          ۱. مدل‌هایی که روی این اکانت اصلاً وجود ندارند (۴۰۴ قطعی)
          ۲. مدل‌هایی که در همین اجرا سهمیهٔ روزانه‌شان تمام شده
        این‌طوری وقتی سهمیهٔ مدل اول تمام می‌شود، *درجا* و بدون هیچ sleep
        به مدل بعدی می‌رویم.

        روی موفقیت، اسم مدلی که واقعاً جواب داد در ``response.model``
        گذاشته می‌شود تا لایهٔ بالا بتواند لاگ دقیق بزند.
        """
        # بدون تکراری، ولی ترتیب حفظ شود: اول مدل درخواستی، بعد جایگزین‌ها.
        requested = tuple(dict.fromkeys((model, *fallback_models)))

        # ۱) مدل‌هایی که اصلاً روی این اکانت وجود ندارند را حذف کن، تا
        #    بی‌خودی ۴۰۴ نزنیم و سهمیه/زمان هدر نرود.
        available = self.list_models()
        if available:
            models = tuple(m for m in requested if m in available)
            skipped = [m for m in requested if m not in available]
            if skipped:
                logger.info("این مدل‌ها روی اکانت وجود ندارند، رد شدند: %s", skipped)
        else:
            models = requested

        if not models:
            raise GeminiNoModelsAvailable(
                f"هیچ‌کدام از این مدل‌ها روی اکانت تو در دسترس نیست: {list(requested)}"
            )

        # ۲) مدل‌های سهمیه‌تمام‌شده را همین‌جا رد کن (بدون هیچ درخواست شبکه).
        if self._exhausted:
            alive = tuple(m for m in models if m not in self._exhausted)
            if not alive:
                raise GeminiQuotaExhausted(
                    "سهمیهٔ روزانهٔ همهٔ مدل‌های در دسترس در این اجرا تمام شده: "
                    f"{sorted(self._exhausted)}"
                )
            dropped = [m for m in models if m in self._exhausted]
            logger.info(
                "سهمیهٔ روزانهٔ این مدل‌ها قبلاً در همین اجرا تمام شده بود، رد شدند: %s",
                dropped,
            )
            models = alive

        last_error: Exception | None = None

        for index, candidate in enumerate(models):
            try:
                response = self._generate_with_retry(candidate, contents, config)
                _remember_model(response, candidate)
                return response
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
                raise GeminiError(f"هیچ مدل در دسترس نبود: {list(models)}") from exc
            except GeminiQuotaExhausted as exc:
                last_error = exc
                # ثبت در مدارشکن تا بقیهٔ فراخوانی‌های همین اجرا درجا ردش کنند.
                self._exhausted.add(candidate)
                if index + 1 < len(models):
                    logger.warning(
                        "سهمیهٔ روزانهٔ %s تمام شده؛ *بدون صبر* امتحان مدل %s "
                        "(سهمیهٔ هر مدل جداست)",
                        candidate,
                        models[index + 1],
                    )
                    continue
                raise GeminiError(
                    "سهمیهٔ روزانهٔ همهٔ مدل‌های در دسترس تمام شده: "
                    f"{list(models)}"
                ) from exc
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
                    # مدل وجود ندارد: retry بی‌فایده است، درجا برو مدل بعدی.
                    if _is_missing_model(exc):
                        raise GeminiUnavailable(f"مدل {model} پیدا نشد: {exc}") from exc

                    # سهمیهٔ روزانه تمام شده؟ صبر کردن روی همین مدل فایده ندارد؛
                    # سریع برگرد بیرون تا مدل بعدی امتحان شود.
                    if is_daily_quota_exhausted(exc):
                        raise GeminiQuotaExhausted(
                            f"سهمیهٔ روزانهٔ {model} تمام شده است: {exc}"
                        ) from exc

                    if attempt >= self.max_retries or not _is_retryable(exc):
                        raise GeminiError(f"فراخوانی {model} شکست خورد: {exc}") from exc

                    # محدودیت دقیقه‌ای (RPM/TPM) با صبر کوتاه حل می‌شود، پس
                    # برای ۴۲۹ کمی سخاوتمندانه‌تر صبر می‌کنیم.
                    if is_quota_error(exc):
                        delay = min(30.0, (2 ** attempt) * 5.0) + random.uniform(0, 2.0)
                    else:
                        delay = min(20.0, (2 ** (attempt - 1)) * 2.0) + random.uniform(0, 1.5)

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
