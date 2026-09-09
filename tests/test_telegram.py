"""تست لایهٔ تلگرام با Session جعلی (بدون شبکه)."""

from __future__ import annotations

import json

import pytest

from bioai_channel.telegram import CAPTION_LIMIT, TelegramClient, TelegramError


class FakeHTTPResponse:
    def __init__(self, payload, status_code=200, raw_text=None):
        self._payload = payload
        self.status_code = status_code
        if raw_text is not None:
            self.text = raw_text
        elif isinstance(payload, Exception):
            self.text = "not-json"
        else:
            self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        if isinstance(self._payload, Exception):
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent: list[dict] = []
        self.headers = {}

    def post(self, url, json=None, data=None, files=None, timeout=None):
        # کپی می‌گیریم چون لایهٔ واقعی ممکن است payload را بعداً تغییر دهد
        # (مثلاً parse_mode را در fallback حذف می‌کند).
        import copy

        self.sent.append(
            {
                "url": url,
                "json": copy.deepcopy(json),
                "data": copy.deepcopy(data),
                "files": files,
            }
        )
        item = self.responses.pop(0) if self.responses else {"ok": True, "result": {"message_id": 1}}
        if isinstance(item, Exception):
            raise item
        if isinstance(item, FakeHTTPResponse):
            return item
        return FakeHTTPResponse(item)


def make_client(responses):
    session = FakeSession(responses)
    client = TelegramClient(bot_token="TOKEN", chat_id="@chan", session=session, max_retries=3)
    return client, session


def test_send_message_returns_message_id():
    client, session = make_client([{"ok": True, "result": {"message_id": 42}}])
    assert client.send_message("سلام") == 42
    payload = session.sent[0]["json"]
    assert payload["parse_mode"] == "HTML"
    assert payload["chat_id"] == "@chan"
    assert "api.telegram.org/botTOKEN/sendMessage" in session.sent[0]["url"]


def test_link_preview_option_is_serialised():
    client, session = make_client([{"ok": True, "result": {"message_id": 1}}])
    client.send_message("x", link_preview=True)
    opts = json.loads(session.sent[0]["json"]["link_preview_options"])
    assert opts["is_disabled"] is False


def test_falls_back_to_plain_text_on_parse_error():
    client, session = make_client(
        [
            {"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"},
            {"ok": True, "result": {"message_id": 7}},
        ]
    )
    assert client.send_message("<b>bad") == 7
    assert "parse_mode" in session.sent[0]["json"]
    assert "parse_mode" not in session.sent[1]["json"]


def test_429_waits_and_retries(monkeypatch):
    slept = []
    monkeypatch.setattr("bioai_channel.telegram.time.sleep", lambda s: slept.append(s))
    client, session = make_client(
        [
            {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 4}},
            {"ok": True, "result": {"message_id": 9}},
        ]
    )
    assert client.send_message("x") == 9
    assert slept and slept[0] >= 4


def test_error_raises_with_description():
    client, _session = make_client(
        [{"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}]
    )
    with pytest.raises(TelegramError) as exc:
        client.send_message("x")
    assert "chat not found" in str(exc.value)


def test_too_long_text_is_rejected_before_network():
    client, session = make_client([])
    with pytest.raises(TelegramError):
        client.send_message("ک" * 5000)
    assert session.sent == []


def test_inline_keyboard_is_serialised():
    client, session = make_client([{"ok": True, "result": {"message_id": 1}}])
    client.send_message("x", reply_markup={"inline_keyboard": [[{"text": "a", "url": "https://x"}]]})
    markup = json.loads(session.sent[0]["json"]["reply_markup"])
    assert markup["inline_keyboard"][0][0]["url"] == "https://x"


def test_reply_parameters_serialised():
    client, session = make_client([{"ok": True, "result": {"message_id": 2}}])
    client.send_message("x", reply_to_message_id=11)
    assert json.loads(session.sent[0]["json"]["reply_parameters"]) == {"message_id": 11}


def test_send_photo_uses_multipart():
    client, session = make_client([{"ok": True, "result": {"message_id": 3}}])
    photo_id = client.send_photo(b"\x89PNG\r\n", caption="کپشن", reply_to_message_id=1)
    assert photo_id == 3
    assert session.sent[0]["files"] is not None
    assert session.sent[0]["data"]["caption"] == "کپشن"


def test_send_photo_truncates_caption():
    client, session = make_client([{"ok": True, "result": {"message_id": 3}}])
    client.send_photo(b"x", caption="a" * 3000)
    assert len(session.sent[0]["data"]["caption"]) == CAPTION_LIMIT


def test_send_photo_rejects_oversized_image():
    client, _session = make_client([])
    with pytest.raises(TelegramError):
        client.send_photo(b"x" * (11 * 1024 * 1024))


def test_non_json_response_retries(monkeypatch):
    monkeypatch.setattr("bioai_channel.telegram.time.sleep", lambda *_: None)
    client, session = make_client(
        [FakeHTTPResponse(ValueError("nope"), 502), {"ok": True, "result": {"message_id": 5}}]
    )
    assert client.send_message("x") == 5
    assert len(session.sent) == 2


def test_http_500_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("bioai_channel.telegram.time.sleep", lambda *_: None)
    client, session = make_client(
        [
            {"ok": False, "error_code": 500, "description": "Internal Server Error"},
            {"ok": True, "result": {"message_id": 8}},
        ]
    )
    assert client.send_message("x") == 8
    assert len(session.sent) == 2


def test_silent_flag():
    client, session = make_client([{"ok": True, "result": {"message_id": 1}}])
    client.send_message("x", silent=True)
    assert session.sent[0]["json"]["disable_notification"] is True


def test_ok_true_without_message_id_raises():
    client, _session = make_client([{"ok": True, "result": {}}])
    with pytest.raises(TelegramError):
        client.send_message("x")
