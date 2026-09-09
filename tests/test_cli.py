"""تست نقطهٔ ورود CLI — مسیر واقعی main() با کلاینت‌های جعلی."""

from __future__ import annotations

import json

import pytest

from bioai_channel import main as cli


class FakeGemini:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, model, contents, config):
        self.calls += 1
        modalities = getattr(config, "response_modalities", None)
        if modalities:
            inline = type("I", (), {"data": b"\x89PNG" + b"0" * 32, "mime_type": "image/png"})()
            return type("R", (), {"parts": [type("P", (), {"inline_data": inline})()], "usage_metadata": None, "candidates": []})()
        grounding = type("G", (), {"grounding_chunks": [], "web_search_queries": None, "search_entry_point": None})()
        return type(
            "R",
            (),
            {
                "text": json.dumps(self.payload, ensure_ascii=False),
                "usage_metadata": None,
                "candidates": [type("C", (), {"grounding_metadata": grounding})()],
            },
        )()


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.photos = []

    def send_message(self, text, **kwargs):
        self.sent.append(text)
        return 500 + len(self.sent)

    def send_photo(self, photo_bytes, **kwargs):
        self.photos.append(len(photo_bytes))
        return 600 + len(self.photos)

    def me(self):
        return {"username": "test_bot", "id": 1}

    def chat_info(self):
        return {"type": "channel", "title": "Test Channel", "id": -100}

    def _call(self, method, payload):
        return [{"user": {"id": 1}}]


PAYLOAD = {
    "topic_slug": "smoke",
    "title": "تیتر تست دود",
    "hook": "قلاب",
    "body": ["پاراگراف اول.", "پاراگراف دوم."],
    "sources": [{"title": "منبع", "url": "https://www.nature.com/x"}],
    "hashtags": ["تست"],
    "buttons": [],
    "image_prompt": "a test cell",
}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@test_channel")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setenv("SKIP_SIGNALS", "true")
    return tmp_path


def test_dry_run_returns_zero(env, monkeypatch, capsys):
    fake_gemini = FakeGemini(PAYLOAD)
    fake_telegram = FakeTelegram()
    monkeypatch.setattr(cli, "GeminiClient", lambda **kwargs: fake_gemini)
    monkeypatch.setattr(cli, "TelegramClient", lambda **kwargs: fake_telegram)

    code = cli.main(["--dry-run", "--format", "fact"])
    out = capsys.readouterr().out

    assert code == 0
    assert fake_telegram.sent == []  # در dry run چیزی ارسال نمی‌شود
    assert "تیتر تست دود" in out
    assert '"ok": true' in out


def test_real_run_sends(env, monkeypatch):
    fake_gemini = FakeGemini(PAYLOAD)
    fake_telegram = FakeTelegram()
    monkeypatch.setattr(cli, "GeminiClient", lambda **kwargs: fake_gemini)
    monkeypatch.setattr(cli, "TelegramClient", lambda **kwargs: fake_telegram)

    code = cli.main(["--format", "deepdive"])

    assert code == 0
    assert len(fake_telegram.sent) >= 1
    assert len(fake_telegram.photos) == 1
    assert (env / "memory.json").exists()


def test_missing_env_fails_cleanly(monkeypatch, capsys):
    for key in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)
    code = cli.main(["--dry-run"])
    assert code == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_selftest(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "GeminiClient", lambda **kwargs: FakeGemini(PAYLOAD))
    monkeypatch.setattr(cli, "TelegramClient", lambda **kwargs: FakeTelegram())
    code = cli.main(["--selftest"])
    out = capsys.readouterr().out
    assert code == 0
    assert "test_bot" in out


def test_admin_notification_on_failure(env, monkeypatch):
    class BrokenTelegram(FakeTelegram):
        def send_message(self, text, **kwargs):
            from bioai_channel.telegram import TelegramError

            raise TelegramError("chat not found")

    monkeypatch.setattr(cli, "GeminiClient", lambda **kwargs: FakeGemini(PAYLOAD))
    monkeypatch.setattr(cli, "TelegramClient", lambda **kwargs: BrokenTelegram())
    monkeypatch.setenv("ADMIN_CHAT_ID", "12345")

    code = cli.main(["--format", "fact"])
    assert code == 1


def test_no_image_flag(env, monkeypatch):
    fake_gemini = FakeGemini(PAYLOAD)
    fake_telegram = FakeTelegram()
    monkeypatch.setattr(cli, "GeminiClient", lambda **kwargs: fake_gemini)
    monkeypatch.setattr(cli, "TelegramClient", lambda **kwargs: fake_telegram)

    code = cli.main(["--format", "fact", "--no-image"])
    assert code == 0
    assert fake_telegram.photos == []


def test_unknown_format_rejected_by_argparse(env):
    with pytest.raises(SystemExit):
        cli.main(["--format", "does_not_exist"])
