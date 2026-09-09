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
        api_keys: tuple[str, ...] = (),
    ) -> None:
        self.max_retries = max(1, max_retries)
        self.timeout = timeout

        # هر ورودی ممکن است شامل چند key با newline/comma/semicolon باشد.
        # هر key را به‌صورت مستقل به google-genai می‌دهیم تا multiline
        # به‌عنوان مقدار یک HTTP header ارسال نشود.
        raw_values = [api_key, *api_keys]
        split_keys: list[str] = []
        for raw in raw_values:
            if not raw:
                continue
            split_keys.extend(
                item.strip()
                for item in re.split(r"[,;

]+", str(raw))
                if item.strip()
            )
        keys = tuple(dict.fromkeys(split_keys))

        self._api_keys = keys
        self._clients: list[Any] = []
        self._model_caches: list[set[str] | None] = []
        self._exhausted_by_key: list[set[str]] = []
        self._active_key_index = 0

        # سازگاری کامل با تست‌ها و کد قبلی: _client همان کلاینت اول است.
        if client is not None:
            self._clients = [client]
        else:
            from google import genai
            from google.genai import types

            self._clients = [
                genai.Client(
                    api_key=key,
                    http_options=types.HttpOptions(timeout=timeout * 1000),
                )
                for key in self._api_keys
            ]

        if not self._clients:
            raise ValueError("حداقل یک GEMINI API key لازم است.")

        self._client = self._clients[0]
        self._model_caches = [None for _ in self._clients]
        self._exhausted_by_key = [set() for _ in self._clients]

        # aliases برای سازگاری با تست‌ها و نسخه‌های قبلی
        self._model_cache: set[str] | None = None
        self._exhausted: set[str] = self._exhausted_by_key[0]

    # ------------------------------------------------------------------ API
    def _client_for_key(self, key_index: int) -> Any:
        return self._clients[key_index]

    def _list_models_for_key(self, key_index: int) -> set[str] | None:
        """مدل‌های قابل مشاهده برای یک API key را cache می‌کند."""
        cached = self._model_caches[key_index]
        if cached is not None:
            return cached

        names: set[str] = set()
        try:
            for page in self._client_for_key(key_index).models.list():
                name = str(getattr(page, "name", "") or "")
                if name:
                    names.add(name.replace("models/", ""))
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "گرفتن فهرست مدل‌ها برای API key #%d ممکن نشد: %s",
                key_index + 1,
                exc,
            )
            self._model_caches[key_index] = None
            return None

        self._model_caches[key_index] = names or None
        if names:
            logger.info(
                "%d مدل روی API key #%d در دسترس است.",
                len(names),
                key_index + 1,
            )
        return self._model_caches[key_index]

    def list_models(self) -> set[str] | None:
        """مدل‌های قابل مشاهده روی کل key pool را برمی‌گرداند."""
        union: set[str] = set()
        any_success = False
        for i in range(len(self._clients)):
            names = self._list_models_for_key(i)
            if names is not None:
                any_success = True
                union.update(names)

        # aliases برای سازگاری
        self._model_cache = union or None
        return union if any_success and union else None

    def exhausted_models(self) -> frozenset[str]:
        """مدل‌هایی که روی API key فعال/اول سهمیهٔ روزانه‌شان تمام شده."""
        return frozenset(self._exhausted_by_key[self._active_key_index])

    def exhausted_key_indexes(self) -> frozenset[int]:
        """کلیدهایی که فعلاً تمام مدل‌های ladder آن‌ها quota-exhausted شده."""
        return frozenset(
            i for i, exhausted in enumerate(self._exhausted_by_key)
            if exhausted
        )

    def _ordered_models_for_key(
        self, key_index: int, requested: tuple[str, ...]
    ) -> tuple[str, ...]:
        available = self._list_models_for_key(key_index)
        if not available:
            return requested

        confirmed = tuple(m for m in requested if m in available)
        unconfirmed = tuple(m for m in requested if m not in available)
        if unconfirmed:
            logger.info(
                "برای API key #%d این مدل‌ها در فهرست دیده نشدند و آخر صف "
                "امتحان می‌شوند: %s",
                key_index + 1,
                list(unconfirmed),
            )
        return confirmed + unconfirmed

    def _generate_on_key(
        self,
        key_index: int,
        requested: tuple[str, ...],
        contents: Any,
        config: Any,
    ) -> Any:
        """کل ladder را فقط با یک API key اجرا می‌کند."""
        exhausted = self._exhausted_by_key[key_index]
        models = self._ordered_models_for_key(key_index, requested)
        alive = tuple(m for m in models if m not in exhausted)

        if not alive:
            raise GeminiQuotaExhausted(
                f"سهمیهٔ روزانهٔ همهٔ مدل‌های API key #{key_index + 1} "
                f"در این اجرا تمام شده: {list(models)}"
            )

        last_error: Exception | None = None
        original_client = self._client
        self._client = self._client_for_key(key_index)
        try:
            for index, candidate in enumerate(alive):
                try:
                    response = self._generate_with_retry(candidate, contents, config)
                    _remember_model(response, candidate)
                    try:
                        object.__setattr__(response, "api_key_index", key_index + 1)
                    except Exception:
                        pass
                    return response
                except GeminiUnavailable as exc:
                    last_error = exc
                    if index + 1 < len(alive):
                        logger.warning(
                            "مدل %s با API key #%d در دسترس نبود؛ امتحان %s",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )
                        continue
                    raise
                except GeminiQuotaExhausted as exc:
                    last_error = exc
                    exhausted.add(candidate)
                    if index + 1 < len(alive):
                        logger.warning(
                            "سهمیهٔ روزانهٔ %s روی API key #%d تمام شد؛ "
                            "بدون صبر به مدل %s می‌رویم.",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )
                        continue
                    raise
                except GeminiError as exc:
                    last_error = exc
                    if index + 1 < len(alive):
                        logger.warning(
                            "مدل %s با API key #%d شکست خورد؛ امتحان %s",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )
                        continue
                    raise
        finally:
            self._client = original_client

        raise GeminiError(
            f"فراخوانی Gemini با API key #{key_index + 1} ناموفق بود: {last_error}"
        )

    def generate(
        self,
        model: str,
        contents: Any,
        config: Any,
        fallback_models: tuple[str, ...] = (),
    ) -> Any:
        """تولید با مدل‌لدر + failover بین چند API key.

        ترتیب:
        1) برای هر key، مدل درخواستی و fallbackها امتحان می‌شوند.
        2) اگر quota روزانهٔ همهٔ مدل‌های آن key تمام شد، key بعدی فعال می‌شود.
        3) روی 429 روزانه هیچ sleep انجام نمی‌شود.
        4) 429 دقیقه‌ای همچنان با backoff retry می‌شود.

        نکته: این قابلیت برای چند key/پروژهٔ مجاز است و سهمیهٔ هر پروژه را
        به‌صورت مستقل failover می‌کند؛ استفاده از چند key برای دور زدن
        محدودیت‌های قراردادی سرویس مجاز نیست.
        """
        requested = tuple(dict.fromkeys((model, *fallback_models)))
        if not requested:
            raise GeminiNoModelsAvailable("هیچ مدل Gemini برای اجرا مشخص نشده است.")

        # از آخرین key موفق شروع می‌کنیم تا در اجرای بعدی هم توزیع بهتر شود.
        order = tuple(
            dict.fromkeys(
                (self._active_key_index,)
                + tuple(i for i in range(len(self._clients)))
            )
        )

        key_errors: list[str] = []
        for key_index in order:
            try:
                response = self._generate_on_key(
                    key_index, requested, contents, config
                )
                self._active_key_index = key_index
                return response
            except GeminiQuotaExhausted as exc:
                key_errors.append(f"key#{key_index + 1}: {exc}")
                logger.warning(
                    "تمام مسیرهای مدل برای API key #%d به quota خورد؛ "
                    "به API key بعدی می‌رویم.",
                    key_index + 1,
                )
                continue
            except GeminiUnavailable as exc:
                key_errors.append(f"key#{key_index + 1}: {exc}")
                # اگر هیچ مدل روی این key کار نکرد، key بعدی را هم امتحان کن.
                continue
            except GeminiError as exc:
                key_errors.append(f"key#{key_index + 1}: {exc}")
                # خطاهای موقتی/سایر خطاها نیز در key بعدی failover می‌شوند.
                continue

        # همهٔ keyها بررسی شده‌اند.
        all_exhausted = all(
            set(requested).issubset(exhausted)
            for exhausted in self._exhausted_by_key
        )
        if all_exhausted:
            raise GeminiQuotaExhausted(
                "سهمیهٔ روزانهٔ همهٔ مدل‌های در دسترس روی همهٔ API keyها تمام شده است: "
                f"{list(requested)}"
            )

        raise GeminiError(
            "فراخوانی Gemini با همهٔ API keyهای تنظیم‌شده ناموفق بود: "
            + " | ".join(key_errors)
        )

    def _generate_with_retry(self, model: str, contents: Any, config: Any) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:  # noqa: BLE001
                if _is_missing_model(exc):
                    raise GeminiUnavailable(f"مدل {model} پیدا نشد: {exc}") from exc

                if is_daily_quota_exhausted(exc):
                    raise GeminiQuotaExhausted(
                        f"سهمیهٔ روزانهٔ {model} تمام شده است: {exc}"
                    ) from exc

                if attempt >= self.max_retries or not _is_retryable(exc):
                    raise GeminiError(f"فراخوانی {model} شکست خورد: {exc}") from exc

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
