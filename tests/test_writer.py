"""تست نویسندهٔ پست با کلاینت جعلی Gemini (بدون شبکه)."""

from __future__ import annotations

import json

import pytest

from bioai_channel.config import Settings
from bioai_channel.content.formats import get_format
from bioai_channel.content.styles import roll_style
from bioai_channel.gemini_client import GeminiClient
from bioai_channel.jsonish import JsonParseError
from bioai_channel.memory import Memory
from bioai_channel.signals import Signal, SignalBundle, as_prompt_block
from bioai_channel.writer import build_prompt, write_post


class FakeResponse:
    def __init__(self, text: str, grounded: bool = True):
        self.text = text
        self.usage_metadata = type(
            "U", (), {"total_token_count": 100, "prompt_token_count": 80, "candidates_token_count": 20}
        )()
        chunk = type("C", (), {"retrieved_context": {"uri": "https://x"}})()
        grounding = type(
            "G",
            (),
            {
                "grounding_chunks": [chunk] if grounded else [],
                "web_search_queries": None,
                "search_entry_point": None,
            },
        )()
        self.candidates = [type("Cand", (), {"grounding_metadata": grounding})()]


class FakeRateLimitError(Exception):
    status_code = 429


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self.replies.pop(0) if self.replies else FakeResponse("{}")
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, replies):
        self.models = FakeModels(replies)


def make_settings(**overrides) -> Settings:
    base = dict(
        gemini_api_key="k",
        telegram_bot_token="t",
        telegram_chat_id="@c",
        dry_run=True,
        skip_signals=True,
        state_path="",
    )
    base.update(overrides)
    return Settings(**base)


def good_payload() -> dict:
    return {
        "topic_slug": "rna-structure",
        "title": "تیتر نمونه",
        "hook": "قلاب",
        "body": ["پاراگراف اول.", "پاراگراف دوم."],
        "code_snippet": "",
        "sources": [
            {"title": "یک مقاله", "url": "https://www.nature.com/articles/x"},
            {"title": "یک پیش‌چاپ", "url": "https://www.biorxiv.org/content/y"},
        ],
        "hashtags": ["بیوانفورماتیک"],
        "buttons": [{"text": "مخزن", "url": "https://github.com/a/b"}],
        "image_prompt": "a folded RNA molecule, scientific illustration",
        "silent": False,
    }


def run_writer(replies, fmt_id="deepdive", **settings_kwargs):
    client = GeminiClient("k", client=FakeClient(replies), **settings_kwargs.pop("client_kwargs", {}))
    return write_post(
        client,
        make_settings(**settings_kwargs),
        get_format(fmt_id),
        roll_style(),
        SignalBundle(),
        Memory(path=""),
    )


def test_writes_valid_draft():
    draft, meta = run_writer([FakeResponse(json.dumps(good_payload(), ensure_ascii=False))])
    assert draft.title == "تیتر نمونه"
    assert len(draft.body) == 2
    assert len(draft.sources) == 2
    assert draft.buttons[0]["url"].startswith("https://")
    assert draft.image_prompt
    assert meta["grounded"] is True


def test_prompt_contains_style_signals_and_format():
    bundle = SignalBundle(trends=[Signal("GoogleTrends/US", "protein folding", "https://t")])
    prompt = build_prompt(get_format("breaking"), roll_style(), as_prompt_block(bundle), Memory(path=""))
    assert "POST FORMAT FOR THIS POST" in prompt
    assert "STYLE BRIEF FOR THIS POST" in prompt
    assert "protein folding" in prompt
    assert "no polls" in prompt.lower()
    assert '"topic_slug"' in prompt


def test_system_instruction_forbids_polls_and_english_prose():
    from bioai_channel.writer import SYSTEM_INSTRUCTION

    assert "No polls" in SYSTEM_INSTRUCTION
    assert "Persian" in SYSTEM_INSTRUCTION
    assert "NEVER invent" in SYSTEM_INSTRUCTION


def test_invalid_json_then_valid_recovers():
    replies = [FakeResponse("این json نیست"), FakeResponse(json.dumps(good_payload(), ensure_ascii=False))]
    draft, _meta = run_writer(replies, fmt_id="fact")
    assert draft.title == "تیتر نمونه"


def test_two_bad_replies_raise():
    with pytest.raises(JsonParseError):
        run_writer([FakeResponse("nope"), FakeResponse("still nope")], fmt_id="fact")


def test_missing_sources_for_source_format_raises():
    payload = good_payload()
    payload["sources"] = []
    with pytest.raises(JsonParseError):
        run_writer([FakeResponse(json.dumps(payload, ensure_ascii=False))] * 2, fmt_id="breaking")


def test_format_without_sources_allows_empty():
    payload = good_payload()
    payload["sources"] = []
    draft, _meta = run_writer([FakeResponse(json.dumps(payload, ensure_ascii=False))], fmt_id="fact")
    assert draft.sources == []


def test_empty_title_raises():
    payload = good_payload()
    payload["title"] = "   "
    with pytest.raises(JsonParseError):
        run_writer([FakeResponse(json.dumps(payload, ensure_ascii=False))] * 2, fmt_id="fact")


def test_non_http_sources_are_rejected():
    payload = good_payload()
    payload["sources"] = [{"title": "جعلی", "url": "not-a-url"}]
    with pytest.raises(JsonParseError):
        run_writer([FakeResponse(json.dumps(payload, ensure_ascii=False))] * 2, fmt_id="breaking")


def test_grounding_flag_false_when_no_chunks():
    _draft, meta = run_writer(
        [FakeResponse(json.dumps(good_payload(), ensure_ascii=False), grounded=False)], fmt_id="fact"
    )
    assert meta["grounded"] is False


def test_rate_limit_is_retried_on_same_model(monkeypatch):
    monkeypatch.setattr("bioai_channel.gemini_client.time.sleep", lambda *_: None)
    replies = [FakeRateLimitError(), FakeResponse(json.dumps(good_payload(), ensure_ascii=False))]
    draft, _meta = run_writer(replies, fmt_id="fact", max_retries=3)
    assert draft.title == "تیتر نمونه"


def test_image_prompt_is_passed_through():
    draft, _meta = run_writer([FakeResponse(json.dumps(good_payload(), ensure_ascii=False))], fmt_id="fact")
    assert "RNA" in draft.image_prompt


def test_topic_slug_is_lowercased():
    payload = good_payload()
    payload["topic_slug"] = "Mixed-Case SLUG"
    draft, _meta = run_writer([FakeResponse(json.dumps(payload, ensure_ascii=False))], fmt_id="fact")
    assert draft.topic_slug == "mixed-case slug".replace(" ", "-") or draft.topic_slug.islower()
