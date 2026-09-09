"""تست برنامه‌ریز قالب‌ها (چرخش و عدم تکرار)."""

from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta, timezone

from bioai_channel.content.formats import FORMATS, FORMAT_BY_ID, get_format
from bioai_channel.memory import Memory, PostRecord, fingerprint
from bioai_channel.planner import eligible_formats, weighted_choice


def add(memory: Memory, format_id: str, days_ago: float = 0.0, title: str = "") -> None:
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    title = title or f"{format_id}-{len(memory.posts)}"
    memory.add(
        PostRecord(
            ts=ts.isoformat(),
            format=format_id,
            title=title,
            fingerprint=fingerprint(title),
        )
    )


def test_get_format_and_unknown():
    assert get_format("fact").id == "fact"
    try:
        get_format("nope")
    except ValueError as exc:
        assert "nope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("باید ValueError می‌داد")


def test_no_poll_format_exists():
    """طبق درخواست صاحب کانال، هیچ نظرسنجی‌ای نباید وجود داشته باشد."""
    for fmt in FORMATS:
        assert "poll" not in fmt.id.lower()
        assert "quiz" not in fmt.id.lower()
        assert "نظرسنجی" not in fmt.label


def test_min_gap_blocks_recent_specials():
    memory = Memory(path="")
    add(memory, "on_this_day", days_ago=0.5)
    ids = {f.id for f in eligible_formats(memory)}
    assert "on_this_day" not in ids

    memory2 = Memory(path="")
    add(memory2, "on_this_day", days_ago=30)
    assert "on_this_day" in {f.id for f in eligible_formats(memory2)}


def test_never_picks_same_format_three_times_in_a_row():
    memory = Memory(path="")
    add(memory, "fact")
    add(memory, "fact")
    rng = random.Random(42)
    for _ in range(50):
        decision = weighted_choice(memory, rng)
        assert decision.fmt.id != "fact", decision.reason


def test_distribution_covers_many_formats():
    memory = Memory(path="")
    rng = random.Random(7)
    counter: Counter[str] = Counter()
    for _ in range(400):
        decision = weighted_choice(memory, rng)
        counter[decision.fmt.id] += 1
        add(memory, decision.fmt.id, title=f"t-{len(memory.posts)}")

    # باید تنوع واقعی داشته باشیم، نه یک قالب تکراری.
    assert len(counter) >= len(FORMATS) - 3
    assert counter.most_common(1)[0][1] < 400 * 0.30


def test_all_formats_reachable():
    """با حافظهٔ خالی، هر ۱۵ قالب باید قابل انتخاب باشند."""
    rng = random.Random(1234)
    seen = {weighted_choice(Memory(path=""), rng).fmt.id for _ in range(400)}
    assert seen == {f.id for f in FORMATS}


def test_no_format_starves():
    memory = Memory(path="")
    rng = random.Random(99)
    counter: Counter[str] = Counter()
    for _ in range(500):
        decision = weighted_choice(memory, rng)
        counter[decision.fmt.id] += 1
        add(memory, decision.fmt.id, title=f"t-{len(memory.posts)}")
    for fmt in FORMATS:
        if fmt.min_gap_days == 0:
            assert counter[fmt.id] >= 3, f"{fmt.id} گرسنه ماند: {counter}"


def test_format_ids_unique_and_valid():
    ids = [f.id for f in FORMATS]
    assert len(ids) == len(set(ids))
    assert set(FORMAT_BY_ID) == set(ids)
    for fmt in FORMATS:
        assert fmt.target_chars > 0
        assert fmt.weight > 0
        assert fmt.brief.strip()
