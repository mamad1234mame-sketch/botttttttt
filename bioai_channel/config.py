"""تنظیمات مرکزی پروژه — همه‌چیز از متغیرهای محیطی خوانده می‌شود.

هیچ secret ای داخل کد نوشته نمی‌شود. اگر چیزی لازم باشد و نباشد،
در startup با پیام واضح fail می‌کنیم (نه با KeyError گیج‌کننده).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """وقتی یک متغیر محیطی ضروری تنظیم نشده باشد."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"متغیر محیطی {name} تنظیم نشده است. "
            f"در GitHub Actions → Settings → Secrets and variables → Actions اضافه‌اش کن."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _optional_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} باید عدد باشد، ولی «{raw}» است.") from exc


def _model_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """فهرست مدل‌های جایگزین را از یک متغیر محیطی جدا‌شده با کاما می‌خواند."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    models = tuple(m.strip() for m in raw.split(",") if m.strip())
    return models or default


def _api_key_list(primary_name: str = "GEMINI_API_KEY", pool_name: str = "GEMINI_API_KEYS") -> tuple[str, ...]:
    """کلید اصلی + کلیدهای failover را از env می‌خواند.

    GEMINI_API_KEYS می‌تواند با comma یا newline جدا شود. کلید تکراری
    فقط یک‌بار استفاده می‌شود.
    """
    values: list[str] = []
    primary = os.environ.get(primary_name, "").strip()
    if primary:
        values.append(primary)

    raw = os.environ.get(pool_name, "")
    for item in re.split(r"[,\n\r]+", raw):
        item = item.strip()
        if item:
            values.append(item)

    return tuple(dict.fromkeys(values))


# --------------------------------------------------------------------------
# مدل‌ها
# --------------------------------------------------------------------------

#: مدلی که متن را می‌نویسد و وب را جست‌وجو می‌کند (Grounding with Google Search).
#: مقدار پیش‌فرض یک مدل *stable* است. برای دیدن فهرست زنده:
#: https://ai.google.dev/gemini-api/docs/models
#:
#: توجه (سپتامبر ۲۰۲۶): gemini-2.5-flash و gemini-2.5-flash-lite رسماً
#: shut down شده‌اند (به ترتیب ۱۷ ژوئن و ۲۲ ژوئیهٔ ۲۰۲۶) و دیگر در هیچ
#: نردبانی نباید باشند — همیشه ۴۰۴ می‌دهند و فقط وقت/تلاش هدر می‌دهند.
DEFAULT_TEXT_MODEL = "gemini-3.8-flash"

#: اگر سهمیهٔ مدل اصلی تمام شد (429) یا مدل در دسترس نبود، این‌ها به‌ترتیب
#: امتحان می‌شوند. نکتهٔ مهم: سهمیهٔ هر مدل جداست، پس مدل دوم می‌تواند
#: همان لحظه‌ای که مدل اول 429 داده کار کند.
#:
#: ترتیب: مدل‌های جدیدتر و پایدار خانوادهٔ Gemini 3 اول، بعد Flash-Lite ها
#: (سهمیهٔ رایگانشان معمولاً بالاتر است). مدل‌هایی که روی اکانت وجود ندارند
#: خودکار به آخر صف منتقل می‌شوند (نه حذف — چون فهرست اکانت ممکن است ناقص
#: یا با تأخیر sync شده باشد؛ حذف کامل باعث می‌شد مدل‌های واقعاً کار‌کن هم
#: هرگز امتحان نشوند).
DEFAULT_TEXT_MODEL_FALLBACKS = (
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
)

#: مدل تولید تصویر (Nano Banana 2). اگر روی اکانت تو در دسترس نبود،
#: با IMAGE_MODEL_FALLBACKS امتحان می‌شود و در نهایت پست بدون تصویر می‌رود.
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_MODEL_FALLBACKS = (
    "gemini-3.1-flash-lite-image",
    "gemini-2.5-flash-image",
)

#: مدل‌های *Pro*. پیش‌فرض استفاده نمی‌شوند (سهمیهٔ رایگان‌شان کم است و زود
#: ۴۲۹ می‌دهند). اگر GEMINI_PREFER_PRO=true بگذاری، اول این‌ها امتحان
#: می‌شوند و به‌محض تمام شدن سهمیه *درجا* به Flash/Lite سوئیچ می‌شود.
#: مدل‌هایی که روی اکانت وجود ندارند خودکار رد می‌شوند.
PRO_TEXT_MODELS = (
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
)
PRO_IMAGE_MODELS = (
    "gemini-3-pro-image",
    "gemini-3.1-pro-image",
)


def _dedupe(models: tuple[str, ...]) -> tuple[str, ...]:
    """ترتیب را حفظ می‌کند، تکراری‌ها را حذف."""
    return tuple(dict.fromkeys(models))


@dataclass(slots=True)
class Settings:
    """یک snapshot از تنظیمات؛ راحت قابل تست و قابل override."""

    gemini_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    #: کلیدهای مجاز اضافی برای failover. کلید اصلی هم همیشه در این pool است.
    gemini_api_keys: tuple[str, ...] = ()

    text_model: str = DEFAULT_TEXT_MODEL
    text_model_fallbacks: tuple[str, ...] = DEFAULT_TEXT_MODEL_FALLBACKS
    image_model: str = DEFAULT_IMAGE_MODEL
    image_model_fallbacks: tuple[str, ...] = IMAGE_MODEL_FALLBACKS

    #: اگر true باشد، مدل‌های Pro *اول* امتحان می‌شوند و به‌محض ۴۲۹ به
    #: Flash/Lite سوئیچ می‌شود. پیش‌فرض false است چون سهمیهٔ رایگان Pro کم است.
    prefer_pro: bool = False

    #: ادمین شخصی که گزارش خطاها برایش می‌رود (اختیاری).
    admin_chat_id: str = ""

    #: اگر true باشد، هیچ پیامی به تلگرام نمی‌رود؛ فقط در خروجی چاپ می‌شود.
    dry_run: bool = False
    #: اگر true باشد، تصویر تولید نمی‌شود (صرفه‌جویی در سهمیه).
    skip_images: bool = False
    #: اگر true باشد، سیگنال‌های ترند از اینترنت گرفته نمی‌شوند.
    skip_signals: bool = False

    max_output_tokens: int = 4096
    temperature: float = 0.9
    #: سقف تلاش مجدد برای هر فراخوانی Gemini.
    max_retries: int = 3
    request_timeout: int = 180

    #: مسیر فایل حافظه (تاریخچه پست‌ها برای جلوگیری از تکرار).
    state_path: str = "state/memory.json"

    #: امضای پایانی کانال (می‌تواند خالی باشد).
    signature: str = "🧬 @Bio_with_AI"

    trends_regions: tuple[str, ...] = ("US", "IR")
    trends_geo_fallback: str = ""  # "" یعنی worldwide
    signal_max_items: int = 12
    signal_timeout: int = 12

    extra: dict[str, str] = field(default_factory=dict)

    # -------------------------------------------------------------- نردبان مدل
    @property
    def text_model_ladder(self) -> tuple[str, ...]:
        """ترتیب کامل مدل‌های متنی برای امتحان کردن.

        همیشه اول ``text_model`` (مدل درخواستی) امتحان می‌شود؛ اگر
        ``prefer_pro`` روشن باشد Pro ها بلافاصله بعدش می‌آیند، و در هر دو
        حالت Flash/Lite ها به‌عنوان تور ایمنی آخر صف هستند. یعنی حتی اگر
        Pro گذاشته باشی، با تمام شدن سهمیه‌اش درجا به رایگان می‌افتی.
        """
        head: tuple[str, ...] = (self.text_model,)
        if self.prefer_pro:
            head = head + PRO_TEXT_MODELS
        return _dedupe(head + self.text_model_fallbacks)

    @property
    def image_model_ladder(self) -> tuple[str, ...]:
        """ترتیب کامل مدل‌های تصویر برای امتحان کردن."""
        head: tuple[str, ...] = (self.image_model,)
        if self.prefer_pro:
            head = head + PRO_IMAGE_MODELS
        return _dedupe(head + self.image_model_fallbacks)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=_require("GEMINI_API_KEY"),
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_require("TELEGRAM_CHAT_ID"),
            gemini_api_keys=_api_key_list(),
            text_model=_optional("GEMINI_MODEL", DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL,
            text_model_fallbacks=_model_list(
                "GEMINI_MODEL_FALLBACKS", DEFAULT_TEXT_MODEL_FALLBACKS
            ),
            image_model=_optional("IMAGE_MODEL", DEFAULT_IMAGE_MODEL) or DEFAULT_IMAGE_MODEL,
            image_model_fallbacks=_model_list("IMAGE_MODEL_FALLBACKS", IMAGE_MODEL_FALLBACKS),
            prefer_pro=_optional("GEMINI_PREFER_PRO", "false").lower()
            in {"1", "true", "yes", "on"},
            admin_chat_id=_optional("ADMIN_CHAT_ID"),
            dry_run=_optional("DRY_RUN", "false").lower() in {"1", "true", "yes", "on"},
            skip_images=_optional("SKIP_IMAGES", "false").lower() in {"1", "true", "yes", "on"},
            skip_signals=_optional("SKIP_SIGNALS", "false").lower() in {"1", "true", "yes", "on"},
            max_output_tokens=_optional_int("MAX_OUTPUT_TOKENS", 4096),
            temperature=float(_optional("TEMPERATURE", "0.9") or 0.9),
            max_retries=_optional_int("MAX_RETRIES", 3),
            request_timeout=_optional_int("REQUEST_TIMEOUT", 180),
            state_path=_optional("STATE_PATH", "state/memory.json"),
            signature=_optional("CHANNEL_SIGNATURE", "@Bio_with_AI"),
        )
