"""تست حافظه و تشخیص تکرار."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bioai_channel.memory import Memory, PostRecord, fingerprint


def make_record(format_id: str, title: str, ts: datetime | None = None) -> PostRecord:
    return PostRecord(
        ts=(ts or datetime.now(timezone.utc)).isoformat(),
        format=format_id,
        title=title,
        fingerprint=fingerprint(title),
    )


def test_fingerprint_normalizes_persian_variants():
    a = fingerprint("یادگیری ماشین در ژنومیک")
    b = fingerprint("يادگيري ماشين در ژنوميک")  # ي/ک عربی و بدون نیم‌فاصله
    assert a == b


def test_fingerprint_differs_for_different_titles():
    assert fingerprint("عنوان یک") != fingerprint("عنوان دو")


def test_add_and_recent(tmp_path):
    memory = Memory(path=str(tmp_path / "memory.json"))
    memory.add(make_record("fact", "یک"))
    memory.add(make_record("joke", "دو"))
    assert memory.recent_formats(5) == ["fact", "joke"]


def test_save_and_reload(tmp_path):
    path = str(tmp_path / "state" / "memory.json")
    memory = Memory(path=path)
    memory.add(make_record("deepdive", "عنوان"))
    assert memory.save() is True

    reloaded = Memory.load(path)
    assert len(reloaded.posts) == 1
    assert reloaded.posts[0].format == "deepdive"


def test_load_missing_file_is_empty(tmp_path):
    memory = Memory.load(str(tmp_path / "nope.json"))
    assert memory.posts == []


def test_load_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{ این json نیست", encoding="utf-8")
    memory = Memory.load(str(path))
    assert memory.posts == []


def test_is_duplicate_detects_same_content(tmp_path):
    memory = Memory(path="")
    fp = fingerprint("عنوان تکراری", "بدنه")
    memory.add(PostRecord(ts=datetime.now(timezone.utc).isoformat(), format="fact", title="عنوان تکراری", fingerprint=fp))
    assert memory.is_duplicate(fp) is True
    assert memory.is_duplicate("ffffffffffffffff") is False


def test_days_since_format():
    memory = Memory(path="")
    old = datetime.now(timezone.utc) - timedelta(days=7)
    memory.add(make_record("on_this_day", "قدیمی", old))
    gap = memory.days_since_format("on_this_day")
    assert gap is not None and 6.9 <= gap <= 7.1
    assert memory.days_since_format("never_used") is None


def test_format_counts():
    memory = Memory(path="")
    memory.add(make_record("fact", "۱"))
    memory.add(make_record("fact", "۲"))
    memory.add(make_record("joke", "۳"))
    assert memory.format_counts(10) == {"fact": 2, "joke": 1}


def test_titles_digest_empty():
    assert "هنوز" in Memory(path="").titles_digest()
