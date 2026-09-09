"""تست تولید تصویر: نردبان مدل‌ها و سوئیچ درجا روی سهمیه.

رگرسیونِ مهم: قبلاً image.py بدون fallback_models صدا می‌زد، پس وقتی سهمیهٔ
مدل تصویر تمام می‌شد کل مسیر تصویر می‌مرد و پست بدون تصویر می‌رفت.
"""

from __future__ import annotations

import base64

import pytest

from bioai_channel import image as image_module
from bioai_channel.config import Settings
from bioai_channel.content.styles import StyleRoll
from bioai_channel.gemini_client import GeminiClient, GeminiError

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


class Err(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class InlineData:
    def __init__(self, data=PNG_1PX, mime_type="image/png"):
        self.data = data
        self.mime_type = mime_type


class Part:
    def __init__(self, inline_data=None, text=None):
        self.inline_data = inline_data
        self.text = text


class ImageResponse:
    """پاسخی که یک تصویر داخلش است."""

    def __init__(self, data=PNG_1PX):
        self.parts = [Part(inline_data=InlineData(data))]
        self.usage_metadata = None
        self.candidates = []


class TextOnlyResponse:
    """پاسخی که تصویر ندارد (فقط متن)."""

    text = "sorry"

    def __init__(self):
        self.parts = [Part(inline_data=None, text="sorry")]
        self.usage_metadata = None
        self.candidates = []


class FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.script.pop(0) if self.script else ImageResponse()
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


@pytest.fixture(autouse=True)
def record_sleep(monkeypatch):
    """هر sleep ثبت می‌شود تا بتوانیم ثابت کنیم سوئیچ *بدون صبر* است."""
    slept: list[float] = []
    monkeypatch.setattr("bioai_channel.gemini_client.time.sleep", slept.append)
    return slept


@pytest.fixture
def style():
    return StyleRoll(
        opening="hook",
        title_style="plain",
        emoji_family=("🧬",),
        ending_style="question",
        image_style="flat vector",
        image_mood="calm",
        seed=1,
    )


def _settings(**overrides) -> Settings:
    base = dict(
        gemini_api_key="k",
        telegram_bot_token="t",
        telegram_chat_id="@c",
        image_model="img-a",
        image_model_fallbacks=("img-b", "img-c"),
        state_path="",
    )
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------- نردبان مدل‌ها
def test_image_ladder_is_model_then_fallbacks():
    s = _settings()
    assert s.image_model_ladder == ("img-a", "img-b", "img-c")


def test_image_ladder_no_duplicates():
    s = _settings(image_model="img-a", image_model_fallbacks=("img-a", "img-b"))
    assert s.image_model_ladder == ("img-a", "img-b")


def test_prefer_pro_puts_pro_first_but_keeps_free_safety_net():
    s = _settings(prefer_pro=True)
    ladder = s.image_model_ladder
    assert ladder[0] == "img-a"
    assert "gemini-3-pro-image" in ladder
    # تور ایمنی رایگان باید همچنان آخر صف باشد
    assert ladder[-1] == "img-c"


def test_pro_not_used_by_default():
    s = _settings()
    assert "gemini-3-pro-image" not in s.image_model_ladder
    assert "gemini-3.1-pro-preview" not in s.text_model_ladder


# ------------------------------------------------------------- سوئیچ روی سهمیه
def test_image_falls_back_when_quota_exhausted(record_sleep, style):
    """سهمیهٔ روزانه که تمام شد، *درجا* برود مدل بعدی — بدون هیچ sleep."""
    settings = _settings()
    daily = Err(
        "429 RESOURCE_EXHAUSTED. You exceeded your current quota. "
        "Model gemini-3.1-flash-image has a free daily limit. "
        "Requests will reset at midnight Pacific Time.",
        429,
    )
    client = GeminiClient("k", max_retries=3, client=FakeClient([daily, ImageResponse()]))

    result = image_module.generate(client, settings, "ribosome structure", style)

    assert result is not None, "تصویر باید با مدل جایگزین ساخته شود"
    # باگ قبلی: فقط مدل اول صدا زده می‌شد
    assert client._client.models.calls == ["img-a", "img-b"]
    # حیاتی: هیچ صبری نباید داشته باشیم، سوئیچ باید آنی باشد
    assert record_sleep == [], f"سوئیچ باید درجا باشد ولی صبر کردیم: {record_sleep}"


def test_image_skips_missing_model_without_calling_it(style):
    """مدلی که روی اکانت نیست اصلاً صدا زده نشود (۴۰۴ قطعی)."""
    settings = _settings()
    client = GeminiClient("k", max_retries=3, client=FakeClient([ImageResponse()]))

    class FakeModel:
        def __init__(self, name):
            self.name = name

    class FakeLister:
        def __init__(self):
            self.calls = 0

        def list(self):
            self.calls += 1
            return [FakeModel("models/img-b"), FakeModel("models/img-c")]

    lister = FakeLister()
    client._client.models.lister = lister
    client._client.models.list = lister.list

    result = image_module.generate(client, settings, "topic", style)
    assert result is not None
    assert client._client.models.calls == ["img-b"], "img-a وجود ندارد، نباید صدا زده شود"


class StrictModels(FakeModels):
    """اگر مدلی از فهرست ممنوعه صدا زده شود، بلافاصله تست را می‌ترکاند."""

    def __init__(self, script, banned=()):
        super().__init__(script)
        self.banned = set(banned)

    def generate_content(self, model, contents, config):
        assert model not in self.banned, (
            f"{model} سهمیه‌اش تمام شده بود و نباید دیگر صدا زده می‌شد"
        )
        return super().generate_content(model, contents, config)


def test_image_exhausted_model_is_not_retried_by_later_calls(style):
    """مدارشکن: مدلی که سهمیه‌اش تمام شده در فراخوانی بعدی هم رد می‌شود."""
    settings = _settings()
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    models = StrictModels([daily, daily, ImageResponse()])
    client = GeminiClient("k", max_retries=3, client=FakeClient([]))
    client._client.models = models

    first = image_module.generate(client, settings, "topic", style)
    assert first is not None
    assert models.calls == ["img-a", "img-b", "img-c"]
    assert client.exhausted_models() == frozenset({"img-a", "img-b"})

    # فراخوانی دوم: img-a و img-b ممنوع‌اند؛ StrictModels در صورت صدا زده
    # شدنشان AssertionError می‌دهد. پس فقط img-c باید کار کند.
    models.banned = {"img-a", "img-b"}
    models.calls.clear()
    models.script = [ImageResponse()]
    second = image_module.generate(client, settings, "topic", style)
    assert second is not None
    assert models.calls == ["img-c"]


def test_text_and_image_share_the_same_circuit_breaker(style, settings_factory):
    """اگر متن سهمیهٔ مدلی را تمام کرد، تصویر هم دیگر آن را صدا نزند."""
    settings = settings_factory(
        text_model="shared-a",
        text_model_fallbacks=("shared-b",),
        image_model="shared-a",
        image_model_fallbacks=("shared-b", "img-c"),
    )
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    models = StrictModels([daily, ImageResponse()])
    client = GeminiClient("k", max_retries=3, client=FakeClient([]))
    client._client.models = models

    # فراخوانی متنی: shared-a سهمیه‌اش تمام می‌شود، shared-b جواب می‌دهد.
    client.generate("shared-a", "hi", None, fallback_models=settings.text_model_ladder[1:])
    assert models.calls == ["shared-a", "shared-b"]

    # حالا تصویر: shared-a باید درجا رد شود.
    models.banned = {"shared-a"}
    models.calls.clear()
    models.script = [ImageResponse()]
    assert image_module.generate(client, settings, "topic", style) is not None
    assert models.calls == ["shared-b"]


def test_image_returns_none_when_every_model_is_exhausted(style):
    settings = _settings()
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    client = GeminiClient(
        "k", max_retries=3, client=FakeClient([daily, daily, daily])
    )
    assert image_module.generate(client, settings, "topic", style) is None
    assert client._client.models.calls == ["img-a", "img-b", "img-c"]


def test_image_moves_on_when_model_returns_no_image(style):
    """مدل جواب داد ولی تصویر نداد → فقط همان مدل رد شود، بقیه بمانند."""
    settings = _settings()
    client = GeminiClient(
        "k", max_retries=3, client=FakeClient([TextOnlyResponse(), ImageResponse()])
    )
    result = image_module.generate(client, settings, "topic", style)
    assert result is not None
    assert client._client.models.calls == ["img-a", "img-b"]


def test_image_logs_the_model_that_actually_answered(style, caplog):
    settings = _settings()
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    client = GeminiClient("k", max_retries=3, client=FakeClient([daily, ImageResponse()]))

    with caplog.at_level("INFO"):
        image_module.generate(client, settings, "topic", style)

    assert "img-b" in caplog.text


def test_extract_image_decodes_base64_string():
    response = ImageResponse(data=base64.b64encode(PNG_1PX).decode())
    out = image_module._extract_image(response)
    assert out is not None
    assert out.data == PNG_1PX


def test_image_swallows_gemini_error_and_returns_none(style):
    """اگر همهٔ مدل‌ها شکست بخورند، image باید None بدهد نه استثنا."""
    settings = _settings()
    client = GeminiClient(
        "k",
        max_retries=1,
        client=FakeClient([Err("boom", 500), Err("boom", 500), Err("boom", 500)]),
    )
    assert image_module.generate(client, settings, "topic", style) is None
    assert client._client.models.calls == ["img-a", "img-b", "img-c"]
