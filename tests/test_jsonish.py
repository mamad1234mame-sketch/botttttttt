"""تست پارسر JSON."""

from __future__ import annotations

import pytest

from bioai_channel.jsonish import JsonParseError, coerce_str_list, extract_json


def test_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = 'بله حتماً!\n```json\n{"title": "سلام"}\n```\nامیدوارم مفید باشد.'
    assert extract_json(text) == {"title": "سلام"}


def test_prose_around_object():
    text = 'Here you go: {"title": "x", "body": ["a"]} — hope it helps.'
    assert extract_json(text)["title"] == "x"


def test_trailing_comma_is_repaired():
    assert extract_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_smart_quotes_are_repaired():
    assert extract_json('{“a”: “b”}') == {"a": "b"}


def test_array_at_top_level():
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_empty_raises():
    with pytest.raises(JsonParseError):
        extract_json("")


def test_garbage_raises():
    with pytest.raises(JsonParseError):
        extract_json("این اصلاً JSON نیست")


def test_coerce_str_list_from_strings():
    assert coerce_str_list(["a", "b", "a"]) == ["a", "b"]


def test_coerce_str_list_from_dicts():
    value = [{"title": "مقاله", "url": "https://x.test"}, {"name": "ابزار"}]
    assert coerce_str_list(value) == ["مقاله — https://x.test", "ابزار"]


def test_coerce_str_list_from_single_string():
    assert coerce_str_list("تنها") == ["تنها"]


def test_coerce_str_list_respects_limit():
    assert len(coerce_str_list([str(i) for i in range(50)], limit=4)) == 4


def test_coerce_str_list_none():
    assert coerce_str_list(None) == []
