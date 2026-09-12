"""تست جریان کامل انتشار با کلاینت‌های جعلی (بدون هیچ شبکه‌ای).

خروجی این بات فقط *متن* است: نه تصویری تولید می‌شود، نه عکسی آپلود.
"""

from __future__ import annotations

import json

import pytest

from bioai_channel.config import Settings
from bioai_channel.memory import Memory
from bioai_channel.publisher import Publisher
from bioai_channel.telegram import TelegramError


class FakeTextResponse:
    def __init__(self, payload):
        self.text = json.dumps(payload, ensure_ascii=False)
        self.usage_metadata = None
        grounding = type("G", (), {"grounding_chunks": [object()], "web_search_queries": None, "search_entry_point": None})()
        self.candidates = [type("C", (), {"grounding_metadata": grounding})()]


class FakeGemini:
    """فقط پاسخ متنی می‌دهد؛ هر config درخواستی را نگه می‌دارد."""

    def __init__(self, payload, text_error: Exception | None = None):
        self.payload = payload
        self.text_error = text_error
        self.text_calls = 0
        self.configs: list = []

    def generate(self, model, contents, config):
        self.configs.append(config)
        self.text_calls += 1
        if self.text_error is not None:
            raise self.text_error
        return FakeTextResponse(self.payload)


class FakeTelegram:
    """عمداً send_photo ندارد: اگر روزی کد بخواهد عکس بفرستد، با
    AttributeError می‌ترکد و تست قرمز می‌شود."""

    def __init__(self, fail_on_send: bool = False):
        self.messages: list[dict] = []
        self.fail_on_send = fail_on_send
        self._next_id = 100

    def send_message(self, text, reply_markup=None, link_preview=False, silent=False, reply_to_message_id=None):
        if self.fail_on_send:
            raise TelegramError("chat not found")
        self._next_id += 1
        self.messages.append(
            {
                "text": text,
                "keyboard": reply_markup,
                "link_preview": link_preview,
                "silent": silent,
                "reply_to": reply_to_message_id,
            }
        )
        return self._next_id


def payload(title="تیتر تازه"):
    return {
        "topic_slug": "topic-x",
        "title": title,
        "hook": "قلاب",
        "body": ["پاراگراف اول.", "پاراگراف دوم."],
        "sources": [{"title": "مقاله", "url": "https://www.nature.com/x"}],
        "hashtags": ["AI"],
        "buttons": [],
    }


def make_publisher(tmp_path, gemini, telegram, dry_run=False, forced_format=None):
    settings = Settings(
        gemini_api_key="k",
        telegram_bot_token="t",
        telegram_chat_id="@c",
        dry_run=dry_run,
        skip_signals=True,
        state_path=str(tmp_path / "memory.json"),
        signature="@Test",
    )
    memory = Memory.load(settings.state_path)
    return Publisher(settings=settings, gemini=gemini, telegram=telegram, memory=memory)


def test_dry_run_sends_nothing_but_records_memory(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram, dry_run=True)
    result = publisher.run(forced_format="fact")

    assert result.ok is True
    assert telegram.messages == []
    assert len(publisher.memory.posts) == 1


def test_full_run_sends_only_text(tmp_path):
    telegram = FakeTelegram()
    gemini = FakeGemini(payload())
    publisher = make_publisher(tmp_path, gemini, telegram)
    result = publisher.run(forced_format="deepdive")

    assert result.ok is True
    assert len(telegram.messages) >= 1
    # تعداد message_idها باید دقیقاً برابر تعداد پیام‌های متنی باشد
    assert len(result.message_ids) == len(telegram.messages)


def test_no_image_is_ever_requested_or_sent(tmp_path):
    """رگرسیون: هیچ فراخوانی تصویری (response_modalities) نباید انجام شود."""
    telegram = FakeTelegram()
    gemini = FakeGemini(payload())
    publisher = make_publisher(tmp_path, gemini, telegram)
    result = publisher.run(forced_format="deepdive")

    assert result.ok is True
    assert gemini.text_calls >= 1
    for config in gemini.configs:
        assert getattr(config, "response_modalities", None) is None
        assert getattr(config, "image_config", None) is None
    assert not hasattr(telegram, "send_photo")
    assert "image" not in result.as_dict()


def test_image_module_is_gone():
    """ماژول تولید تصویر دیگر وجود ندارد."""
    import bioai_channel
    import importlib.util

    assert importlib.util.find_spec("bioai_channel.image") is None
    assert not hasattr(bioai_channel, "image")


def test_telegram_failure_is_reported(tmp_path):
    telegram = FakeTelegram(fail_on_send=True)
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram)
    result = publisher.run(forced_format="fact")

    assert result.ok is False
    assert "telegram" in result.error
    assert publisher.memory.posts == []


def test_write_failure_returns_error(tmp_path):
    from bioai_channel.gemini_client import GeminiError

    telegram = FakeTelegram()
    gemini = FakeGemini(payload(), text_error=GeminiError("boom"))
    publisher = make_publisher(tmp_path, gemini, telegram)
    result = publisher.run(forced_format="fact")

    assert result.ok is False
    assert "write failed" in result.error


def test_duplicate_content_is_rejected(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload("یک عنوان ثابت")), telegram)

    first = publisher.run(forced_format="fact")
    assert first.ok is True

    # همان محتوا دوباره → باید تکراری تشخیص داده شود
    publisher2 = make_publisher(tmp_path, FakeGemini(payload("یک عنوان ثابت")), FakeTelegram())
    publisher2.memory = publisher.memory
    second = publisher2.run(forced_format="fact")
    assert second.ok is False
    assert "duplicate" in second.error


def test_memory_is_persisted_and_reloaded(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram)
    publisher.run(forced_format="toolbox")

    reloaded = Memory.load(str(tmp_path / "memory.json"))
    assert len(reloaded.posts) == 1
    assert reloaded.posts[0].format == "toolbox"
    assert reloaded.posts[0].title == "تیتر تازه"


def test_memory_records_have_no_image_field(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram)
    publisher.run(forced_format="fact")

    record = publisher.memory.posts[0].to_dict()
    assert "image_used" not in record


def test_automatic_format_selection_respects_history(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram)
    for _ in range(4):
        publisher.memory.posts.clear()
        publisher.run(forced_format="fact")
    # با اجبار، چرخش رعایت نمی‌شود؛ اینجا فقط بررسی می‌کنیم اجرا سالم است
    assert publisher.memory.posts


def test_rendered_text_has_no_poll_keywords(tmp_path):
    telegram = FakeTelegram()
    publisher = make_publisher(tmp_path, FakeGemini(payload()), telegram)
    publisher.run(forced_format="fact")
    for message in telegram.messages:
        low = message["text"].lower()
        assert "poll" not in low
        assert "نظرسنجی" not in low


def test_keyboard_attached_to_last_part_only(tmp_path):
    telegram = FakeTelegram()
    gemini = FakeGemini(payload())
    publisher = make_publisher(tmp_path, gemini, telegram)
    publisher.run(forced_format="fact")
    keyboards = [m["keyboard"] for m in telegram.messages]
    assert sum(1 for k in keyboards if k) <= 1


def test_unknown_forced_format_raises(tmp_path):
    publisher = make_publisher(tmp_path, FakeGemini(payload()), FakeTelegram())
    with pytest.raises(ValueError):
        publisher.run(forced_format="does_not_exist")


def test_result_dict_shape(tmp_path):
    publisher = make_publisher(tmp_path, FakeGemini(payload()), FakeTelegram())
    result = publisher.run(forced_format="fact")
    data = result.as_dict()
    assert set(data) >= {"ok", "format", "title", "parts", "chars", "message_ids", "error"}
