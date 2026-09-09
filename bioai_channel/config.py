"""تنظیمات مرکزی پروژه — همه‌چیز از متغیرهای محیطی خوانده می‌شود.

هیچ secret ای داخل کد نوشته نمی‌شود. اگر چیزی لازم باشد و نباشد،
در startup با پیام واضح fail می‌کنیم (نه با KeyError گیج‌کننده).
"""

from __future__ import annotations

import os
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


# --------------------------------------------------------------------------
# مدل‌ها
# --------------------------------------------------------------------------

#: مدلی که متن را می‌نویسد و وب را جست‌وجو می‌کند (Grounding with Google Search).
#: مقدار پیش‌فرض یک مدل *stable* است. برای دیدن فهرست زنده:
#: https://ai.google.dev/gemini-api/docs/models
DEFAULT_TEXT_MODEL = "gemini-3.7-flash"

#: اگر سهمیهٔ مدل اصلی تمام شد (429) یا مدل در دسترس نبود، این‌ها به‌ترتیب
#: امتحان می‌شوند. نکتهٔ مهم: سهمیهٔ هر مدل جداست، پس مدل دوم می‌تواند
#: همان لحظه‌ای که مدل اول 429 داده کار کند.
#:
#: ترتیب: اول Flash-Lite ها (سهمیهٔ رایگانشان معمولاً بالاتر است)، بعد
#: بقیهٔ Flash ها. مدل‌هایی که روی اکانت وجود ندارند خودکار رد می‌شوند.
DEFAULT_TEXT_MODEL_FALLBACKS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)

#: مدل تولید تصویر (Nano Banana 2). اگر روی اکانت تو در دسترس نبود،
#: با IMAGE_MODEL_FALLBACKS امتحان می‌شود و در نهایت پست بدون تصویر می‌رود.
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_MODEL_FALLBACKS = (
    "gemini-3.1-flash-lite-image",
    "gemini-2.5-flash-image",
    "gemini-2.5-flash",
)


@dataclass(slots=True)
class Settings:
    """یک snapshot از تنظیمات؛ راحت قابل تست و قابل override."""

    gemini_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str

    text_model: str = DEFAULT_TEXT_MODEL
    text_model_fallbacks: tuple[str, ...] = DEFAULT_TEXT_MODEL_FALLBACKS
    image_model: str = DEFAULT_IMAGE_MODEL
    image_model_fallbacks: tuple[str, ...] = IMAGE_MODEL_FALLBACKS

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

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            gemini_api_key=_require("GEMINI_API_KEY"),
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_require("TELEGRAM_CHAT_ID"),
            text_model=_optional("GEMINI_MODEL", DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL,
            text_model_fallbacks=_model_list(
                "GEMINI_MODEL_FALLBACKS", DEFAULT_TEXT_MODEL_FALLBACKS
            ),
            image_model=_optional("IMAGE_MODEL", DEFAULT_IMAGE_MODEL) or DEFAULT_IMAGE_MODEL,
            image_model_fallbacks=_model_list("IMAGE_MODEL_FALLBACKS", IMAGE_MODEL_FALLBACKS),
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
