"""تست نردبان مدل‌ها و تنظیمات مربوط به Pro/رایگان."""

from __future__ import annotations

from bioai_channel.config import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    IMAGE_MODEL_FALLBACKS,
    PRO_IMAGE_MODELS,
    PRO_TEXT_MODELS,
    Settings,
)


def _s(**overrides) -> Settings:
    base = dict(
        gemini_api_key="k",
        telegram_bot_token="t",
        telegram_chat_id="@c",
        state_path="",
    )
    base.update(overrides)
    return Settings(**base)


# ----------------------------------------------------------------- پیش‌فرض‌ها
def test_default_is_free_not_pro():
    """پیش‌فرض باید رایگان باشد؛ Pro هرگز نباید خودکار انتخاب شود."""
    s = _s()
    assert s.text_model == DEFAULT_TEXT_MODEL
    assert "pro" not in DEFAULT_TEXT_MODEL
    assert "pro" not in DEFAULT_IMAGE_MODEL
    assert not any("pro" in m for m in s.text_model_ladder)
    assert not any("pro" in m for m in s.image_model_ladder)


def test_free_ladder_order_is_requested_model_first():
    s = _s()
    assert s.text_model_ladder[0] == DEFAULT_TEXT_MODEL
    assert s.text_model_ladder[1:] == s.text_model_fallbacks
    assert s.image_model_ladder == (DEFAULT_IMAGE_MODEL, *IMAGE_MODEL_FALLBACKS)


def test_ladders_have_no_duplicates():
    s = _s(
        text_model="gemini-3.5-flash",
        text_model_fallbacks=("gemini-3.5-flash", "gemini-3.1-flash-lite"),
        image_model="img-a",
        image_model_fallbacks=("img-a", "img-b", "img-b"),
    )
    assert s.text_model_ladder == ("gemini-3.5-flash", "gemini-3.1-flash-lite")
    assert s.image_model_ladder == ("img-a", "img-b")


# ------------------------------------------------------------------- حالت Pro
def test_prefer_pro_tries_pro_first_then_falls_to_free():
    """Pro اول، ولی رایگان‌ها همیشه به‌عنوان تور ایمنی آخر صف می‌مانند."""
    s = _s(prefer_pro=True)
    text = s.text_model_ladder
    images = s.image_model_ladder

    assert text[0] == DEFAULT_TEXT_MODEL
    # بلافاصله بعد از مدل درخواستی، Pro ها
    assert text[1] == PRO_TEXT_MODELS[0]
    assert PRO_IMAGE_MODELS[0] in images
    # و تور ایمنی رایگان آخر
    assert text[-1] == s.text_model_fallbacks[-1]
    assert images[-1] == s.image_model_fallbacks[-1]


def test_prefer_pro_does_not_drop_the_requested_model():
    s = _s(prefer_pro=True, text_model="gemini-3.6-flash", image_model="img-x")
    assert s.text_model_ladder[0] == "gemini-3.6-flash"
    assert s.image_model_ladder[0] == "img-x"


def test_pro_model_set_into_GEMINI_MODEL_still_has_free_fallbacks():
    """اگر کاربر خودش Pro را انتخاب کرد، رایگان‌ها باید در صف بمانند."""
    s = _s(text_model="gemini-2.5-pro", image_model="gemini-3-pro-image")
    assert s.text_model_ladder[0] == "gemini-2.5-pro"
    assert "gemini-3.5-flash-lite" in s.text_model_ladder
    assert s.image_model_ladder[0] == "gemini-3-pro-image"
    assert IMAGE_MODEL_FALLBACKS[-1] in s.image_model_ladder


# --------------------------------------------------------------- متغیر محیطی
def test_prefer_pro_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@c")

    monkeypatch.setenv("GEMINI_PREFER_PRO", "true")
    assert Settings.from_env().prefer_pro is True

    monkeypatch.setenv("GEMINI_PREFER_PRO", "0")
    assert Settings.from_env().prefer_pro is False

    monkeypatch.delenv("GEMINI_PREFER_PRO")
    assert Settings.from_env().prefer_pro is False


def test_model_ladders_respect_env_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@c")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACKS", "gemini-3.5-flash-lite, gemini-3.1-flash-lite")
    monkeypatch.setenv("IMAGE_MODEL", "gemini-3.1-flash-image")
    monkeypatch.setenv("IMAGE_MODEL_FALLBACKS", "gemini-2.5-flash-image")

    s = Settings.from_env()
    assert s.text_model_ladder == (
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    )
    assert s.image_model_ladder == ("gemini-3.1-flash-image", "gemini-2.5-flash-image")
