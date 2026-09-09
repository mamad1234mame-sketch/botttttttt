"""تست کلاینت Gemini: retry، fallback، تشخیص خطا."""

from __future__ import annotations

import pytest

from bioai_channel.gemini_client import (
    GeminiClient,
    GeminiError,
    GeminiUnavailable,
    grounding_used,
    usage_of,
)


class Err(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class FakeResponse:
    text = "ok"
    usage_metadata = None
    candidates = []


class FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[str] = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.script.pop(0) if self.script else FakeResponse()
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, script):
        self.models = FakeModels(script)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("bioai_channel.gemini_client.time.sleep", lambda *_: None)


def test_success_first_try():
    client = GeminiClient("k", client=FakeClient([FakeResponse()]))
    assert client.generate("m1", "hi", None).text == "ok"
    assert client._client.models.calls == ["m1"]


def test_retries_on_429_then_succeeds():
    script = [Err("RESOURCE_EXHAUSTED", 429), Err("rate limit", 429), FakeResponse()]
    client = GeminiClient("k", max_retries=3, client=FakeClient(script))
    assert client.generate("m1", "hi", None).text == "ok"
    assert client._client.models.calls == ["m1", "m1", "m1"]


def test_retries_on_503():
    client = GeminiClient("k", max_retries=2, client=FakeClient([Err("unavailable", 503), FakeResponse()]))
    assert client.generate("m1", "hi", None).text == "ok"


def test_non_retryable_error_raises_immediately():
    client = GeminiClient("k", max_retries=5, client=FakeClient([Err("bad request", 400)]))
    with pytest.raises(GeminiError):
        client.generate("m1", "hi", None)
    assert client._client.models.calls == ["m1"]


def test_exhausted_retries_raise():
    script = [Err("RESOURCE_EXHAUSTED", 429)] * 3
    client = GeminiClient("k", max_retries=3, client=FakeClient(script))
    with pytest.raises(GeminiError):
        client.generate("m1", "hi", None)
    assert len(client._client.models.calls) == 3


def test_404_marks_model_unavailable_and_falls_back():
    script = [Err("models/m1 is not found for API version v1beta", 404), FakeResponse()]
    client = GeminiClient("k", max_retries=1, client=FakeClient(script))
    result = client.generate("m1", "hi", None, fallback_models=("m2",))
    assert result.text == "ok"
    assert client._client.models.calls == ["m1", "m2"]


def test_all_models_unavailable_raises():
    script = [Err("models/x is not found", 404)] * 2
    client = GeminiClient("k", max_retries=1, client=FakeClient(script))
    with pytest.raises(GeminiError):
        client.generate("m1", "hi", None, fallback_models=("m2",))


def test_usage_of_handles_missing_metadata():
    assert usage_of(FakeResponse()) == "usage=n/a"


def test_grounding_used_detects_chunks():
    chunk = object()
    grounding = type("G", (), {"grounding_chunks": [chunk], "web_search_queries": None, "search_entry_point": None})()
    response = type("R", (), {"candidates": [type("C", (), {"grounding_metadata": grounding})()]})()
    assert grounding_used(response) is True


def test_grounding_used_false_when_empty():
    grounding = type("G", (), {"grounding_chunks": [], "web_search_queries": None, "search_entry_point": None})()
    response = type("R", (), {"candidates": [type("C", (), {"grounding_metadata": grounding})()]})()
    assert grounding_used(response) is False


def test_grounding_used_false_without_candidates():
    assert grounding_used(FakeResponse()) is False


def test_unavailable_type_is_gemini_error():
    assert issubclass(GeminiUnavailable, GeminiError)
