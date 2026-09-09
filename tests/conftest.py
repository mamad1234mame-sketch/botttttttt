"""تنظیمات مشترک تست‌ها.

اگر SDK واقعی google-genai نصب نباشد، یک stub سبک جای آن را می‌گیرد تا
تست‌ها بدون شبکه و بدون کلید API اجرا شوند.
"""

from __future__ import annotations

import sys
import types as pytypes

import pytest


def _install_stub_genai() -> None:
    if "google.genai" in sys.modules:
        return
    try:  # اگر SDK واقعی هست، از همان استفاده کن.
        import google.genai  # noqa: F401

        return
    except Exception:  # noqa: BLE001
        pass

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Tool:
        def __init__(self, google_search=None, **kwargs):
            self.google_search = google_search

    class GoogleSearch:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ImageConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class HttpOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Client:  # pragma: no cover - در تست‌ها استفاده نمی‌شود
        def __init__(self, *args, **kwargs):
            raise AssertionError("Client واقعی نباید در تست ساخته شود")

    fake_types = pytypes.ModuleType("google.genai.types")
    fake_types.GenerateContentConfig = GenerateContentConfig
    fake_types.Tool = Tool
    fake_types.GoogleSearch = GoogleSearch
    fake_types.ImageConfig = ImageConfig
    fake_types.HttpOptions = HttpOptions

    fake_genai = pytypes.ModuleType("google.genai")
    fake_genai.types = fake_types
    fake_genai.Client = Client

    google_mod = sys.modules.get("google")
    if google_mod is None:
        google_mod = pytypes.ModuleType("google")
        sys.modules["google"] = google_mod
    google_mod.genai = fake_genai

    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_types


_install_stub_genai()


@pytest.fixture
def settings_factory():
    """یک Settings تستی بدون نیاز به متغیر محیطی."""
    from bioai_channel.config import Settings

    def _make(**overrides):
        base = dict(
            gemini_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_chat_id="@test_channel",
            dry_run=True,
            skip_signals=True,
            state_path="",
            signature="@TestChannel",
        )
        base.update(overrides)
        return Settings(**base)

    return _make
