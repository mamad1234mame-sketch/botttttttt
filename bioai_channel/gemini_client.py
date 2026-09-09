"""کلاینت مقاوم Gemini.

امکانات:
    - retry روی خطاهای موقتی
    - تشخیص 429 روزانه در برابر RPM/TPM
    - fallback بین مدل‌ها
    - fallback بین چند API key
    - مدارشکن برای مدل‌هایی که quota روزانه‌شان تمام شده
    - cache فهرست مدل‌ها برای هر API key
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


RETRYABLE_STATUS = {
    429,
    500,
    502,
    503,
    504,
}


RETRYABLE_MARKERS = (
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "unavailable",
    "internal error",
    "deadline exceeded",
)


PER_MINUTE_MARKERS = (
    "per minute",
    "requests per min",
    "tokens per minute",
    "tokens per min",
    "_rpm",
    "_tpm",
)


DAILY_QUOTA_MARKERS = (
    "exceeded your current quota",
    "requests per day",
    "per day",
    "daily limit",
    "free daily limit",
    "quota will reset",
    "_rpd",
)


ZERO_QUOTA_RE = re.compile(
    r"\blimit:?\s*0\b",
    re.IGNORECASE,
)


class GeminiError(RuntimeError):
    pass


class GeminiUnavailable(GeminiError):
    """مدل در دسترس نبود."""


class GeminiQuotaExhausted(GeminiError):
    """سهمیهٔ روزانهٔ مدل/API key تمام شده."""


class GeminiNoModelsAvailable(GeminiError):
    """هیچ مدل قابل استفاده‌ای پیدا نشد."""


def _status_of(exc: Exception) -> int | None:
    for attr in (
        "status_code",
        "code",
    ):
        value = getattr(
            exc,
            attr,
            None,
        )

        if isinstance(value, int):
            return value

    return None


def _is_retryable(exc: Exception) -> bool:

    status = _status_of(exc)

    if status in RETRYABLE_STATUS:
        return True

    message = str(exc).lower()

    return any(
        marker in message
        for marker in RETRYABLE_MARKERS
    )


def is_quota_error(exc: Exception) -> bool:

    message = str(exc).lower()

    return (
        "resource_exhausted" in message
        or "exceeded your current quota" in message
    )


def is_daily_quota_exhausted(
    exc: Exception,
) -> bool:
    """تشخیص quota روزانه از RPM/TPM."""

    message = str(exc).lower()

    # RPM/TPM باید retry شود.
    if any(
        marker in message
        for marker in PER_MINUTE_MARKERS
    ):
        return False

    if any(
        marker in message
        for marker in DAILY_QUOTA_MARKERS
    ):
        return True

    return bool(
        ZERO_QUOTA_RE.search(message)
    )


def _is_missing_model(
    exc: Exception,
) -> bool:

    status = _status_of(exc)

    if status == 404:
        return True

    message = str(exc).lower()

    return (
        "models/ is not found" in message
        or "is not found for api version" in message
        or "invalid model" in message
    )


def _remember_model(
    response: Any,
    model: str,
) -> None:

    try:
        object.__setattr__(
            response,
            "model_used",
            model,
        )

    except Exception:

        try:
            setattr(
                response,
                "model_used",
                model,
            )

        except Exception:
            pass


class GeminiClient:
    """کلاینت Gemini با model fallback و API-key fallback."""

    def __init__(
        self,
        api_key: str,
        max_retries: int = 3,
        timeout: int = 180,
        client: Any | None = None,
        api_keys: tuple[str, ...] = (),
    ) -> None:

        self.max_retries = max(
            1,
            max_retries,
        )

        self.timeout = timeout

        # ----------------------------------------------------------
        # API key pool
        # ----------------------------------------------------------

        keys = tuple(
            dict.fromkeys(
                k.strip()
                for k in api_keys
                if k and k.strip()
            )
        )

        if not keys:

            if api_key.strip():
                keys = (
                    api_key.strip(),
                )

        elif (
            api_key.strip()
            and api_key.strip() not in keys
        ):

            keys = (
                api_key.strip(),
                *keys,
            )

        self._api_keys = keys

        # ----------------------------------------------------------
        # ساخت clientها
        # ----------------------------------------------------------

        self._clients: list[Any] = []

        if client is not None:

            # حالت تست/سازگاری قدیمی
            self._clients = [
                client
            ]

        else:

            from google import genai
            from google.genai import types

            self._clients = [
                genai.Client(
                    api_key=key,
                    http_options=types.HttpOptions(
                        timeout=timeout * 1000
                    ),
                )
                for key in self._api_keys
            ]

        if not self._clients:
            raise ValueError(
                "حداقل یک Gemini API key لازم است."
            )

        # ----------------------------------------------------------
        # cache و state برای هر key
        # ----------------------------------------------------------

        self._model_caches: list[
            set[str] | None
        ] = [
            None
            for _ in self._clients
        ]

        self._exhausted_by_key: list[
            set[str]
        ] = [
            set()
            for _ in self._clients
        ]

        self._active_key_index = 0

        # ----------------------------------------------------------
        # سازگاری با نسخه قبلی
        # ----------------------------------------------------------

        self._client = self._clients[0]

        self._model_cache: set[str] | None = None

        self._exhausted = (
            self._exhausted_by_key[0]
        )

    # ==============================================================
    # MODEL LIST
    # ==============================================================

    def _client_for_key(
        self,
        key_index: int,
    ) -> Any:

        return self._clients[key_index]

    def _list_models_for_key(
        self,
        key_index: int,
    ) -> set[str] | None:
        """فهرست مدل‌های یک API key."""

        cached = self._model_caches[
            key_index
        ]

        if cached is not None:
            return cached

        names: set[str] = set()

        try:

            for page in self._client_for_key(
                key_index
            ).models.list():

                name = str(
                    getattr(
                        page,
                        "name",
                        "",
                    )
                    or ""
                )

                if name:
                    names.add(
                        name.replace(
                            "models/",
                            "",
                        )
                    )

        except Exception as exc:

            logger.debug(
                "گرفتن فهرست مدل‌ها برای API key #%d "
                "ممکن نشد: %s",
                key_index + 1,
                exc,
            )

            self._model_caches[
                key_index
            ] = None

            return None

        self._model_caches[
            key_index
        ] = names or None

        if names:

            logger.info(
                "%d مدل روی API key #%d در دسترس است.",
                len(names),
                key_index + 1,
            )

        return self._model_caches[
            key_index
        ]

    def list_models(self) -> set[str] | None:
        """مدل‌های قابل مشاهده روی همهٔ API keyها."""

        union: set[str] = set()

        any_success = False

        for i in range(
            len(self._clients)
        ):

            names = self._list_models_for_key(
                i
            )

            if names is not None:

                any_success = True

                union.update(names)

        self._model_cache = (
            union or None
        )

        if any_success and union:
            return union

        return None

    # ==============================================================
    # STATE
    # ==============================================================

    def exhausted_models(
        self,
    ) -> frozenset[str]:
        """مدل‌های quota-exhausted روی key فعال."""

        return frozenset(
            self._exhausted_by_key[
                self._active_key_index
            ]
        )

    def exhausted_key_indexes(
        self,
    ) -> frozenset[int]:
        """Keyهایی که حداقل یک مدلشان exhausted شده."""

        return frozenset(
            i
            for i, exhausted
            in enumerate(
                self._exhausted_by_key
            )
            if exhausted
        )

    # ==============================================================
    # MODEL ORDER
    # ==============================================================

    def _ordered_models_for_key(
        self,
        key_index: int,
        requested: tuple[str, ...],
    ) -> tuple[str, ...]:

        available = self._list_models_for_key(
            key_index
        )

        # اگر list API جواب نداد،
        # مدل‌ها را حذف نکن.
        if not available:
            return requested

        confirmed = tuple(
            m
            for m in requested
            if m in available
        )

        unconfirmed = tuple(
            m
            for m in requested
            if m not in available
        )

        if unconfirmed:

            logger.info(
                "برای API key #%d این مدل‌ها در فهرست "
                "دیده نشدند و آخر صف امتحان می‌شوند: %s",
                key_index + 1,
                list(unconfirmed),
            )

        return (
            confirmed
            + unconfirmed
        )

    # ==============================================================
    # ONE KEY
    # ==============================================================

    def _generate_on_key(
        self,
        key_index: int,
        requested: tuple[str, ...],
        contents: Any,
        config: Any,
    ) -> Any:
        """کل model ladder را روی یک API key اجرا می‌کند."""

        exhausted = (
            self._exhausted_by_key[
                key_index
            ]
        )

        models = self._ordered_models_for_key(
            key_index,
            requested,
        )

        alive = tuple(
            m
            for m in models
            if m not in exhausted
        )

        if not alive:

            raise GeminiQuotaExhausted(
                f"سهمیهٔ روزانهٔ همهٔ مدل‌های "
                f"API key #{key_index + 1} "
                f"در این اجرا تمام شده: "
                f"{list(models)}"
            )

        last_error: Exception | None = None

        original_client = self._client

        self._client = (
            self._client_for_key(
                key_index
            )
        )

        try:

            for index, candidate in enumerate(
                alive
            ):

                try:

                    response = self._generate_with_retry(
                        candidate,
                        contents,
                        config,
                    )

                    _remember_model(
                        response,
                        candidate,
                    )

                    try:

                        object.__setattr__(
                            response,
                            "api_key_index",
                            key_index + 1,
                        )

                    except Exception:
                        pass

                    return response

                except GeminiUnavailable as exc:

                    last_error = exc

                    if (
                        index + 1
                        < len(alive)
                    ):

                        logger.warning(
                            "مدل %s با API key #%d "
                            "در دسترس نبود؛ امتحان %s",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )

                        continue

                    raise

                except GeminiQuotaExhausted as exc:

                    last_error = exc

                    exhausted.add(
                        candidate
                    )

                    if (
                        index + 1
                        < len(alive)
                    ):

                        logger.warning(
                            "سهمیهٔ روزانهٔ %s روی API key #%d "
                            "تمام شد؛ بدون صبر به مدل %s می‌رویم.",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )

                        continue

                    raise

                except GeminiError as exc:

                    last_error = exc

                    if (
                        index + 1
                        < len(alive)
                    ):

                        logger.warning(
                            "مدل %s با API key #%d شکست خورد؛ "
                            "امتحان %s",
                            candidate,
                            key_index + 1,
                            alive[index + 1],
                        )

                        continue

                    raise

        finally:

            self._client = (
                original_client
            )

        raise GeminiError(
            f"فراخوانی Gemini با API key "
            f"#{key_index + 1} ناموفق بود: "
            f"{last_error}"
        )

    # ==============================================================
    # PUBLIC GENERATE
    # ==============================================================

    def generate(
        self,
        model: str,
        contents: Any,
        config: Any,
        fallback_models: tuple[str, ...] = (),
    ) -> Any:
        """تولید با model ladder و API-key failover.

        ترتیب کلی:

        API key #1
            model 1
            model 2
            model 3
            ...

        API key #2
            model 1
            model 2
            model 3
            ...

        API key #3
            ...

        اگر quota روزانه یک مدل تمام شود:
            sleep = 0
            مدل بعدی فوراً امتحان می‌شود.

        اگر تمام مدل‌های یک API key quota شوند:
            API key بعدی فوراً امتحان می‌شود.

        نکته:
        استفاده از چند key باید برای پروژه‌ها/credentialهای مجاز باشد.
        این مکانیزم برای دور زدن محدودیت‌های قراردادی سرویس طراحی نشده است.
        """

        requested = tuple(
            dict.fromkeys(
                (
                    model,
                    *fallback_models,
                )
            )
        )

        if not requested:

            raise GeminiNoModelsAvailable(
                "هیچ مدل Gemini برای اجرا مشخص نشده است."
            )

        # key موفق قبلی را اول امتحان کن.
        order = tuple(
            dict.fromkeys(
                (
                    self._active_key_index,
                    *range(
                        len(self._clients)
                    ),
                )
            )
        )

        key_errors: list[str] = []

        for key_index in order:

            try:

                response = self._generate_on_key(
                    key_index,
                    requested,
                    contents,
                    config,
                )

                self._active_key_index = (
                    key_index
                )

                logger.info(
                    "Gemini با API key #%d و مدل %s موفق شد.",
                    key_index + 1,
                    getattr(
                        response,
                        "model_used",
                        "unknown",
                    ),
                )

                return response

            except GeminiQuotaExhausted as exc:

                key_errors.append(
                    f"key#{key_index + 1}: {exc}"
                )

                logger.warning(
                    "تمام مسیرهای مدل برای API key #%d "
                    "به quota خورد؛ API key بعدی امتحان می‌شود.",
                    key_index + 1,
                )

                continue

            except GeminiUnavailable as exc:

                key_errors.append(
                    f"key#{key_index + 1}: {exc}"
                )

                continue

            except GeminiError as exc:

                key_errors.append(
                    f"key#{key_index + 1}: {exc}"
                )

                continue

        # آیا واقعاً تمام مدل‌ها روی همهٔ keyها exhausted هستند؟
        all_exhausted = all(
            set(requested).issubset(
                exhausted
            )
            for exhausted
            in self._exhausted_by_key
        )

        if all_exhausted:

            raise GeminiQuotaExhausted(
                "سهمیهٔ روزانهٔ همهٔ مدل‌های در دسترس "
                "روی همهٔ API keyها تمام شده است: "
                f"{list(requested)}"
            )

        raise GeminiError(
            "فراخوانی Gemini با همهٔ API keyهای "
            "تنظیم‌شده ناموفق بود: "
            + " | ".join(key_errors)
        )

    # ==============================================================
    # RETRY
    # ==============================================================

    def _generate_with_retry(
        self,
        model: str,
        contents: Any,
        config: Any,
    ) -> Any:

        attempt = 0

        while True:

            attempt += 1

            try:

                return self._client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )

            except Exception as exc:

                # --------------------------------------------------
                # مدل وجود ندارد
                # --------------------------------------------------

                if _is_missing_model(exc):

                    raise GeminiUnavailable(
                        f"مدل {model} پیدا نشد: {exc}"
                    ) from exc

                # --------------------------------------------------
                # quota روزانه
                # --------------------------------------------------

                if is_daily_quota_exhausted(
                    exc
                ):

                    raise GeminiQuotaExhausted(
                        f"سهمیهٔ روزانهٔ {model} "
                        f"تمام شده است: {exc}"
                    ) from exc

                # --------------------------------------------------
                # retryable نیست
                # --------------------------------------------------

                if (
                    attempt >= self.max_retries
                    or not _is_retryable(exc)
                ):

                    raise GeminiError(
                        f"فراخوانی {model} شکست خورد: {exc}"
                    ) from exc

                # --------------------------------------------------
                # RPM/TPM
                # --------------------------------------------------

                if is_quota_error(exc):

                    delay = (
                        min(
                            30.0,
                            (2 ** attempt) * 5.0,
                        )
                        + random.uniform(
                            0,
                            2.0,
                        )
                    )

                else:

                    delay = (
                        min(
                            20.0,
                            (2 ** (attempt - 1)) * 2.0,
                        )
                        + random.uniform(
                            0,
                            1.5,
                        )
                    )

                logger.warning(
                    "تلاش %d/%d برای %s شکست خورد (%s). "
                    "%.1f ثانیه صبر می‌کنیم…",
                    attempt,
                    self.max_retries,
                    model,
                    str(exc)[:140],
                    delay,
                )

                time.sleep(delay)


# ==============================================================
# HELPERS
# ==============================================================

def usage_of(
    response: Any,
) -> str:
    """خلاصهٔ مصرف توکن برای لاگ."""

    usage = getattr(
        response,
        "usage_metadata",
        None,
    )

    if usage is None:
        return "usage=n/a"

    total = getattr(
        usage,
        "total_token_count",
        None,
    )

    prompt = getattr(
        usage,
        "prompt_token_count",
        None,
    )

    out = getattr(
        usage,
        "candidates_token_count",
        None,
    )

    return (
        f"usage total={total} "
        f"in={prompt} "
        f"out={out}"
    )


def grounding_used(
    response: Any,
) -> bool:
    """آیا واقعاً Google Search grounding استفاده شده؟"""

    metadata = getattr(
        response,
        "candidates",
        None,
    )

    if not metadata:
        return False

    for candidate in metadata:

        grounding = getattr(
            candidate,
            "grounding_metadata",
            None,
        )

        if grounding is None:
            continue

        if (
            getattr(
                grounding,
                "grounding_chunks",
                None,
            )
            or getattr(
                grounding,
                "web_search_queries",
                None,
            )
        ):

            return True

        if getattr(
            grounding,
            "search_entry_point",
            None,
        ):

            return True

    return False
