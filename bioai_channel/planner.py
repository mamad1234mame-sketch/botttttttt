"""انتخاب قالب پست با قواعد چرخش.

هدف: دو پست پشت‌سرهم شبیه هم نباشند، قالب‌های خاص (مثل «امروز در تاریخ»)
بیش از حد تکرار نشوند، و هیچ قالبی گرسنه نماند.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .content.formats import FORMATS, PostFormat
from .memory import Memory


@dataclass(slots=True)
class PlanDecision:
    fmt: PostFormat
    reason: str


def eligible_formats(memory: Memory, now_formats: tuple[PostFormat, ...] = FORMATS) -> list[PostFormat]:
    """قالب‌هایی که الان مجازند (با احترام به فاصلهٔ زمانی)."""
    out: list[PostFormat] = []
    for fmt in now_formats:
        if fmt.min_gap_days <= 0:
            out.append(fmt)
            continue
        gap = memory.days_since_format(fmt.id)
        if gap is None or gap >= fmt.min_gap_days:
            out.append(fmt)
    return out or list(now_formats)


def weighted_choice(
    memory: Memory,
    rng: random.Random | None = None,
    now_formats: tuple[PostFormat, ...] = FORMATS,
) -> PlanDecision:
    """یک قالب را با وزن و جریمهٔ تکرار انتخاب می‌کند."""
    rng = rng or random.SystemRandom()
    candidates = eligible_formats(memory, now_formats)
    recent = memory.recent_formats(6)

    weights: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for fmt in candidates:
        weight = fmt.weight
        notes: list[str] = []

        # دو پست آخر از یک قالب؟ این قالب را کنار بگذار.
        if len(recent) >= 2 and recent[-1] == fmt.id and recent[-2] == fmt.id:
            weight = 0.0
            notes.append("blocked: 2 بار پشت‌سرهم")
        # در ۶ پست اخیر ۳ بار یا بیشتر آمده؟ نصف وزن.
        elif recent.count(fmt.id) >= 3:
            weight *= 0.5
            notes.append("halved: 3+ بار در ۶ پست اخیر")
        # آخرین پست همین قالب بوده؟ کاهش ملایم.
        elif recent and recent[-1] == fmt.id:
            weight *= 0.45
            notes.append("damped: پست قبلی همین بود")

        # قالب‌های کم‌مصرف را هل بده بالا.
        counts = memory.format_counts(20)
        if counts.get(fmt.id, 0) == 0 and len(memory.posts) >= 3:
            weight *= 1.8
            notes.append("boosted: تا حالا استفاده نشده")

        weights[fmt.id] = weight
        reasons[fmt.id] = notes or ["normal"]

    total = sum(weights.values())
    if total <= 0:
        chosen = rng.choice(candidates)
        return PlanDecision(chosen, "fallback (همه وزن‌ها صفر بودند)")

    pick = rng.uniform(0, total)
    running = 0.0
    for fmt in candidates:
        running += weights[fmt.id]
        if pick <= running:
            return PlanDecision(fmt, "; ".join(reasons[fmt.id]))

    chosen = candidates[-1]
    return PlanDecision(chosen, "fallback")


def pick_forced(format_id: str) -> PlanDecision:
    from .content.formats import get_format

    return PlanDecision(get_format(format_id), "manual override")
