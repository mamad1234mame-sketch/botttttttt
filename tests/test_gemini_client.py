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


# ---------------------------------------------------------------------------
# مدیریت سهمیه (429)
# ---------------------------------------------------------------------------

REAL_QUOTA_MESSAGE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'You exceeded your current quota, please check your plan and billing "
    "details.', 'status': 'RESOURCE_EXHAUSTED'}}"
)


class QuotaError(Exception):
    status_code = 429


def test_detects_daily_quota_exhaustion():
    from bioai_channel.gemini_client import is_daily_quota_exhausted, is_quota_error

    exc = QuotaError(REAL_QUOTA_MESSAGE)
    assert is_quota_error(exc) is True
    assert is_daily_quota_exhausted(exc) is True


def test_rpm_limit_is_not_daily_quota():
    """محدودیت دقیقه‌ای باید retry بخورد، نه اینکه مدل عوض شود."""
    from bioai_channel.gemini_client import is_daily_quota_exhausted, is_quota_error

    exc = QuotaError("429 RESOURCE_EXHAUSTED: requests per minute limit exceeded")
    assert is_quota_error(exc) is True
    assert is_daily_quota_exhausted(exc) is False


def test_daily_quota_immediately_falls_back_to_next_model():
    """با سهمیهٔ روزانه، صبر روی همان مدل بی‌فایده است."""
    from bioai_channel.gemini_client import GeminiQuotaExhausted

    slept: list[float] = []
    import bioai_channel.gemini_client as gc

    original_sleep = gc.time.sleep
    gc.time.sleep = lambda s: slept.append(s)  # type: ignore[assignment]
    try:
        script = [QuotaError(REAL_QUOTA_MESSAGE), FakeResponse()]
        client = GeminiClient("k", max_retries=5, client=FakeClient(script))
        result = client.generate("m1", "hi", None, fallback_models=("m2",))
        assert result.text == "ok"
        assert client._client.models.calls == ["m1", "m2"]
        # نباید روی مدل اول هیچ صبری کرده باشد
        assert slept == []
    finally:
        gc.time.sleep = original_sleep  # type: ignore[assignment]


def test_all_models_quota_exhausted_raises_clear_error():
    from bioai_channel.gemini_client import GeminiError

    script = [QuotaError(REAL_QUOTA_MESSAGE)] * 2
    client = GeminiClient("k", max_retries=3, client=FakeClient(script))
    with pytest.raises(GeminiError) as exc:
        client.generate("m1", "hi", None, fallback_models=("m2",))
    assert "سهمیهٔ روزانهٔ همهٔ مدل‌ها" in str(exc.value)


def test_rpm_429_gets_longer_backoff(monkeypatch):
    """برای محدودیت دقیقه‌ای باید سخاوتمندانه‌تر صبر کنیم."""
    slept: list[float] = []
    monkeypatch.setattr("bioai_channel.gemini_client.time.sleep", lambda s: slept.append(s))
    monkeypatch.setattr("bioai_channel.gemini_client.random.uniform", lambda a, b: 0.0)

    script = [Err("RESOURCE_EXHAUSTED: requests per minute", 429), FakeResponse()]
    client = GeminiClient("k", max_retries=2, client=FakeClient(script))
    assert client.generate("m1", "hi", None).text == "ok"
    assert slept and slept[0] >= 10.0, slept  # (2**1)*5 = 10 ثانیه
    # ولی نباید بی‌دلیل طولانی شود: هدف رسیدنِ سریع به مدل بعدی است.
    assert slept[0] <= 35.0, slept


def test_gemini_quota_exhausted_is_gemini_error():
    from bioai_channel.gemini_client import GeminiQuotaExhausted

    assert issubclass(GeminiQuotaExhausted, GeminiError)


# ---------------------------------------------------------------------------
# کشف مدل‌های موجود روی اکانت
# ---------------------------------------------------------------------------

class FakeModelsList:
    """شبیه‌ساز client.models.list() که اسم مدل‌ها را برمی‌گرداند."""

    def __init__(self, names):
        self.names = names
        self.calls = 0

    def list(self):
        self.calls += 1
        return [type("M", (), {"name": f"models/{n}"})() for n in self.names]


class FakeClientWithList:
    def __init__(self, names, script):
        self.models = FakeModels(script)
        self.lister = FakeModelsList(names)
        self.models.list = self.lister.list


def test_skips_models_not_on_the_account():
    """مدل ۴۰۴‌دهنده نباید اصلاً صدا زده شود."""
    client = GeminiClient(
        "k",
        client=FakeClientWithList(["m-good"], [FakeResponse()]),
    )
    result = client.generate("m-gone", "hi", None, fallback_models=("m-good",))
    assert result.text == "ok"
    # فقط مدل موجود صدا زده شده
    assert client._client.models.calls == ["m-good"]


def test_unconfirmed_models_are_still_attempted_not_dropped():
    """اگر هیچ‌کدام از مدل‌های درخواستی در فهرست اکانت دیده نشوند، حذف
    نمی‌شوند — چون فهرست اکانت می‌تواند ناقص، تأخیردار، یا محدود به
    منطقه/نسخهٔ API باشد (دقیقاً همان چیزی که در عمل رخ داد: مدل‌های ۳.x
    واقعاً کار می‌کردند ولی چون در فهرست دیده نشدند، حذف و هرگز امتحان
    نشدند). باید همچنان روی شبکه امتحان شوند، نه اینکه پیش از هر تلاشی
    با GeminiNoModelsAvailable رد شوند."""
    script = [Err("models/m1 is not found", 404), Err("models/m2 is not found", 404)]
    client = GeminiClient("k", max_retries=1, client=FakeClientWithList(["other-model"], script))
    with pytest.raises(GeminiError):
        client.generate("m1", "hi", None, fallback_models=("m2",))
    # هر دو واقعاً روی شبکه امتحان شده‌اند، نه اینکه پیش از تلاش رد شوند.
    assert client._client.models.calls == ["m1", "m2"]


def test_confirmed_models_are_still_tried_before_unconfirmed_ones():
    """مدل‌های تأییدشده توسط فهرست اکانت باید اول امتحان شوند، ولی
    مدل‌های تأییدنشده هم به‌عنوان چارهٔ آخر در صف می‌مانند."""
    client = GeminiClient(
        "k",
        client=FakeClientWithList(["m-good"], [FakeResponse()]),
    )
    # ترتیب درخواستی: اول m-unlisted (که در فهرست نیست)، بعد m-good.
    result = client.generate("m-unlisted", "hi", None, fallback_models=("m-good",))
    assert result.text == "ok"
    # با اینکه m-unlisted اول درخواست شده بود، چون تأیید نشده به آخر رفته
    # و m-good (تأییدشده) اول امتحان شده است.
    assert client._client.models.calls == ["m-good"]


def test_model_list_is_cached():
    fake = FakeClientWithList(["m1"], [FakeResponse(), FakeResponse()])
    client = GeminiClient("k", client=fake)
    client.generate("m1", "a", None)
    client.generate("m1", "b", None)
    assert fake.lister.calls == 1, "فهرست مدل‌ها باید فقط یک‌بار گرفته شود"


def test_strips_models_prefix():
    client = GeminiClient("k", client=FakeClientWithList(["gemini-3.7-flash"], [FakeResponse()]))
    names = client.list_models()
    assert names == {"gemini-3.7-flash"}
    assert all(not n.startswith("models/") for n in names)


def test_list_models_returns_none_when_api_fails():
    """اگر گرفتن فهرست نشد، باید سخت‌گیری نکنیم."""

    class Broken:
        def list(self):
            raise RuntimeError("boom")

    class BrokenClient:
        def __init__(self):
            self.models = FakeModels([FakeResponse()])
            self.models.list = Broken().list

    client = GeminiClient("k", client=BrokenClient())
    assert client.list_models() is None
    # و generate هنوز کار کند
    assert client.generate("m1", "hi", None).text == "ok"


def test_404_model_still_falls_back_when_no_list():
    """اگر فهرست در دسترس نبود، مسیر قدیمی ۴۰۴→fallback باید کار کند."""
    script = [Err("models/m1 is not found", 404), FakeResponse()]
    client = GeminiClient("k", max_retries=1, client=FakeClient(script))
    result = client.generate("m1", "hi", None, fallback_models=("m2",))
    assert result.text == "ok"
    assert client._client.models.calls == ["m1", "m2"]


# ------------------------------------------------------- تشخیص نوع ۴۲۹
DAILY_MSGS = [
    "429 RESOURCE_EXHAUSTED. {'error': {'message': 'You exceeded your current quota.'}}",
    "RESOURCE_EXHAUSTED: free daily limit reached for model gemini-3.7-flash",
    "quota exceeded: requests per day limit is 100",
    "Daily limit reached. Quota will reset at midnight Pacific Time.",
    "{'quotaMetric': 'generative_language_api_rpd', 'quota_limit_values': {'limit': 0}}",
]

MINUTE_MSGS = [
    "429 RESOURCE_EXHAUSTED. You exceeded your current quota: requests per minute",
    "RESOURCE_EXHAUSTED: tokens per minute limit reached",
    "{'quotaMetric': 'generative_language_api_rpm', 'quota_limit_values': {'limit': 10}}",
]


@pytest.mark.parametrize("msg", DAILY_MSGS)
def test_daily_quota_detected(msg):
    """همهٔ شکل‌های پیام «سهمیهٔ روزانه» باید درجا سوئیچ کنند."""
    from bioai_channel.gemini_client import is_daily_quota_exhausted

    assert is_daily_quota_exhausted(Err(msg, 429)), msg


@pytest.mark.parametrize("msg", MINUTE_MSGS)
def test_minute_limit_is_not_daily_quota(msg):
    """محدودیت دقیقه‌ای با صبر حل می‌شود؛ نباید «تمام شده» تلقی شود."""
    from bioai_channel.gemini_client import is_daily_quota_exhausted

    assert not is_daily_quota_exhausted(Err(msg, 429)), msg


def test_daily_quota_switches_without_sleeping(monkeypatch):
    """مهم‌ترین تست: سوئیچ به مدل بعدی باید *بدون هیچ صبری* باشد."""
    slept: list[float] = []
    monkeypatch.setattr("bioai_channel.gemini_client.time.sleep", slept.append)

    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    client = GeminiClient("k", max_retries=5, client=FakeClient([daily, daily, FakeResponse()]))
    assert client.generate("m1", "hi", None, fallback_models=("m2", "m3")).text == "ok"
    assert client._client.models.calls == ["m1", "m2", "m3"]
    assert slept == [], f"باید درجا سوئیچ می‌کرد، ولی {slept} ثانیه صبر کرد"


# ------------------------------------------------------------- مدارشکن
def test_exhausted_model_skipped_on_next_call():
    """مدلی که سهمیه‌اش تمام شد، در فراخوانی بعدی اصلاً صدا زده نشود."""

    class BanModels(FakeModels):
        def __init__(self, script, banned=()):
            super().__init__(script)
            self.banned = set(banned)

        def generate_content(self, model, contents, config):
            assert model not in self.banned, f"{model} نباید دیگر صدا زده می‌شد"
            return super().generate_content(model, contents, config)

    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    models = BanModels([daily, FakeResponse()])
    client = GeminiClient("k", max_retries=3, client=FakeClient([]))
    client._client.models = models

    client.generate("m1", "hi", None, fallback_models=("m2",))
    assert client.exhausted_models() == frozenset({"m1"})

    models.banned = {"m1"}
    models.calls.clear()
    models.script = [FakeResponse()]
    client.generate("m1", "hi", None, fallback_models=("m2",))
    assert models.calls == ["m2"]


def test_all_exhausted_raises_before_any_network_call():
    """اگر همه تمام شده باشند، هیچ درخواستی نزن."""
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    models = FakeModels([daily, daily])
    client = GeminiClient("k", max_retries=3, client=FakeClient([]))
    client._client.models = models

    with pytest.raises(GeminiError):
        client.generate("m1", "hi", None, fallback_models=("m2",))
    assert models.calls == ["m1", "m2"]

    models.calls.clear()
    from bioai_channel.gemini_client import GeminiQuotaExhausted

    with pytest.raises(GeminiQuotaExhausted):
        client.generate("m1", "hi", None, fallback_models=("m2",))
    assert models.calls == [], "هیچ درخواست شبکه‌ای نباید زده شود"


# --------------------------------------------------------- مدلِ موفق
def test_response_records_the_model_that_answered():
    daily = Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. requests per day.", 429)
    client = GeminiClient("k", max_retries=3, client=FakeClient([daily, FakeResponse()]))
    response = client.generate("m1", "hi", None, fallback_models=("m2",))
    assert response.model_used == "m2"


def test_duplicate_models_in_ladder_are_collapsed():
    client = GeminiClient("k", max_retries=3, client=FakeClient([FakeResponse()]))
    client.generate("m1", "hi", None, fallback_models=("m1", "m2", "m2", "m1"))
    assert client._client.models.calls == ["m1"]


def test_missing_model_is_not_retried():
    """۴۰۴ قطعی است؛ retry کردنش فقط وقت هدر می‌دهد."""
    missing = Err("404 Not Found. models/gemini-2.5-flash is not found for API version v1beta", 404)
    models = FakeModels([missing, FakeResponse()])
    client = GeminiClient("k", max_retries=5, client=FakeClient([]))
    client._client.models = models
    assert client.generate("dead", "hi", None, fallback_models=("alive",)).text == "ok"
    assert models.calls == ["dead", "alive"], "مدل مرده باید یک‌بار صدا زده شود، نه پنج‌بار"
