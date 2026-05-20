from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from kidage.age import AgeBreakdown, compute, pluralize

PT = timezone(timedelta(hours=-7))
PST = timezone(timedelta(hours=-8))
LA = ZoneInfo("America/Los_Angeles")
NY = ZoneInfo("America/New_York")


def _calendar(age: AgeBreakdown) -> tuple[int, int, int, int]:
    return age.years, age.months, age.days, age.hours


def test_basic_age():
    born = datetime(2022, 9, 12, 3, 47, tzinfo=PT)
    now = datetime(2026, 4, 27, 7, 47, tzinfo=PT)
    assert _calendar(compute(born, now)) == (3, 7, 15, 4)


def test_exact_birthday_minute():
    born = datetime(2022, 9, 12, 3, 47, tzinfo=PT)
    now = datetime(2024, 9, 12, 3, 47, tzinfo=PT)
    assert _calendar(compute(born, now)) == (2, 0, 0, 0)


def test_one_hour_old():
    born = datetime(2026, 4, 27, 6, 0, tzinfo=PT)
    now = datetime(2026, 4, 27, 7, 0, tzinfo=PT)
    assert _calendar(compute(born, now)) == (0, 0, 0, 1)


def test_leap_day_birth():
    # Born Feb 29; in non-leap years dateutil rolls to Feb 28.
    born = datetime(2020, 2, 29, 12, 0, tzinfo=PT)
    now = datetime(2023, 3, 1, 12, 0, tzinfo=PT)
    age = compute(born, now)
    assert age.years == 3
    assert age.months == 0


def test_month_edge():
    # Born Jan 31; one month later is "Feb 28/29".
    born = datetime(2024, 1, 31, 0, 0, tzinfo=PT)
    now = datetime(2024, 2, 29, 0, 0, tzinfo=PT)  # 2024 is leap
    assert _calendar(compute(born, now)) == (0, 1, 0, 0)


def test_requires_tz():
    naive = datetime(2024, 1, 1)
    with pytest.raises(ValueError):
        compute(naive, datetime.now(tz=PT))


def test_rejects_future_birth():
    born = datetime(2030, 1, 1, tzinfo=PT)
    now = datetime(2026, 4, 27, tzinfo=PT)
    with pytest.raises(ValueError):
        compute(born, now)


def test_pluralize():
    assert pluralize(0, "year") == "0 years"
    assert pluralize(1, "year") == "1 year"
    assert pluralize(2, "year") == "2 years"


def test_compute_includes_total_days_and_hours():
    born = datetime(2022, 9, 12, 3, 47, tzinfo=PT)
    now = datetime(2026, 4, 27, 7, 47, tzinfo=PT)
    age = compute(born, now)
    delta = now - born
    assert age.total_days == delta.days
    assert age.total_hours == int(delta.total_seconds() // 3600)


def test_dst_straddle_keeps_wall_clock_anniversary():
    # Born pre-DST in Pacific (-08:00); "now" is post-DST in the same zone
    # (-07:00). At the same wall-clock minute on a monthly anniversary the
    # hours field should be 0, not 23.
    born = datetime(2024, 3, 9, 13, 54, tzinfo=PST).astimezone(LA)
    now = datetime(2026, 4, 9, 13, 54, tzinfo=PT).astimezone(LA)
    assert _calendar(compute(born, now)) == (2, 1, 0, 0)


def test_cross_zone_preserves_birth_instant():
    # Family moves Pacific -> Eastern. The actual moment of birth is fixed,
    # so its wall-clock projection in NY is 3 hours later (16:54 ET). At
    # 13:54 ET on an anniversary day the day hasn't flipped yet.
    born = datetime(2024, 3, 9, 13, 54, tzinfo=PST)
    now = datetime(2026, 4, 9, 13, 54, tzinfo=NY)
    age = compute(born, now)
    assert (age.years, age.months, age.days) == (2, 0, 30)
    assert age.hours == 21


def test_naive_now_rejected():
    """Symmetric to test_requires_tz: a naive `now` must also raise. Otherwise
    age math would silently mix wall-clock and tz-aware datetimes."""
    born = datetime(2024, 1, 1, tzinfo=PT)
    naive_now = datetime(2026, 1, 1)
    with pytest.raises(ValueError):
        compute(born, naive_now)


def test_dst_fall_back_keeps_wall_clock_anniversary():
    """Born during DST (-07:00 in summer), now in standard time (-08:00 in
    winter). At the same wall-clock minute on a monthly anniversary the hours
    field should be 0, not 1 — symmetric to the spring-forward test above."""
    born = datetime(2024, 7, 1, 9, 0, tzinfo=PT).astimezone(LA)
    now = datetime(2026, 12, 1, 9, 0, tzinfo=PST).astimezone(LA)
    assert _calendar(compute(born, now)) == (2, 5, 0, 0)


def test_born_equals_now_is_all_zeros():
    """The literal birth moment: every breakdown field is 0, totals are 0."""
    born = datetime(2026, 5, 20, 12, 0, tzinfo=PT)
    age = compute(born, born)
    assert _calendar(age) == (0, 0, 0, 0)
    assert age.total_days == 0
    assert age.total_hours == 0
