from datetime import datetime, timedelta, timezone

import pytest

from kidage.age import AgeBreakdown
from kidage.special import _ordinal, detect

PT = timezone(timedelta(hours=-7))
BORN = datetime(2022, 9, 12, 3, 47, tzinfo=PT)
MILESTONES = (100, 500, 1000, 2000, 5000)

# Reused age fixtures. The non-special row total_days are deliberately not in
# MILESTONES so that detect() returns None unless the calendar matches.
NORMAL = AgeBreakdown(3, 7, 15, 4, total_days=1324, total_hours=31780)
TURNING_FOUR = AgeBreakdown(4, 0, 0, 0, total_days=1461, total_hours=35064)
NEWBORN = AgeBreakdown(0, 0, 0, 0, total_days=0, total_hours=0)


def test_no_special_day_returns_none():
    now = datetime(2026, 4, 27, 7, 47, tzinfo=PT)
    assert detect(BORN, now, NORMAL, birthday=True, milestones=MILESTONES) is None


def test_birthday_uses_ordinal_for_age():
    now = datetime(2026, 9, 12, 8, 0, tzinfo=PT)
    assert detect(BORN, now, TURNING_FOUR, birthday=True, milestones=MILESTONES) == (
        "Happy 4th Birthday!"
    )


def test_first_birthday_uses_st():
    born = datetime(2025, 4, 27, 6, 0, tzinfo=PT)
    now = datetime(2026, 4, 27, 6, 0, tzinfo=PT)
    age = AgeBreakdown(1, 0, 0, 0, total_days=365, total_hours=8760)
    assert detect(born, now, age, birthday=True, milestones=()) == "Happy 1st Birthday!"


def test_eleventh_birthday_uses_th():
    born = datetime(2015, 6, 1, 0, 0, tzinfo=PT)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=PT)
    age = AgeBreakdown(11, 0, 0, 12, total_days=4018, total_hours=96444)
    assert detect(born, now, age, birthday=True, milestones=()) == "Happy 11th Birthday!"


def test_birth_day_itself_omits_ordinal():
    """Year 0 — the literal day of birth — has no ordinal to celebrate."""
    now = datetime(2022, 9, 12, 18, 0, tzinfo=PT)
    age = AgeBreakdown(0, 0, 0, 14, total_days=0, total_hours=14)
    assert detect(BORN, now, age, birthday=True, milestones=()) == "Happy Birthday!"


def test_birthday_disabled_by_config():
    now = datetime(2026, 9, 12, 8, 0, tzinfo=PT)
    assert detect(BORN, now, TURNING_FOUR, birthday=False, milestones=MILESTONES) is None


def test_leap_day_birth_celebrates_feb_28_in_non_leap_year():
    """On Feb 28 in a non-leap year, a Feb 29 kid is celebrating turning N
    even though dateutil still reports years=N-1 (the real anniversary is the
    next Feb 29). The ordinal follows the year being celebrated."""
    born = datetime(2020, 2, 29, 12, 0, tzinfo=PT)
    now = datetime(2025, 2, 28, 12, 0, tzinfo=PT)  # 2025 is non-leap
    age = AgeBreakdown(4, 11, 30, 0, total_days=1826, total_hours=43824)
    assert detect(born, now, age, birthday=True, milestones=()) == "Happy 5th Birthday!"


def test_birthday_ordinal_correct_before_birth_minute():
    """Bug guard: a kid born at 18:00 must read 'Happy 4th Birthday!' on the
    morning of their 4th birthday, not 'Happy 3rd Birthday!'. The ordinal
    must come from the calendar-year delta, not age.years (which only ticks
    over at the exact birth minute)."""
    born = datetime(2022, 9, 12, 18, 0, tzinfo=PT)
    morning = datetime(2026, 9, 12, 7, 0, tzinfo=PT)  # 11h before birth minute
    # dateutil reports 3y 11m 30d 13h here — age.years lags by a day.
    age = AgeBreakdown(3, 11, 30, 13, total_days=1460, total_hours=35053)
    assert detect(born, morning, age, birthday=True, milestones=()) == "Happy 4th Birthday!"


def test_leap_day_birth_skips_feb_28_in_leap_year():
    """In leap years the real Feb 29 is the birthday — Feb 28 must not also fire."""
    born = datetime(2020, 2, 29, 12, 0, tzinfo=PT)
    feb_28 = datetime(2024, 2, 28, 12, 0, tzinfo=PT)  # 2024 is a leap year
    age = AgeBreakdown(3, 11, 30, 0, total_days=1460, total_hours=35040)
    assert detect(born, feb_28, age, birthday=True, milestones=()) is None


def test_leap_day_birth_fires_on_feb_29_in_leap_year():
    born = datetime(2020, 2, 29, 12, 0, tzinfo=PT)
    feb_29 = datetime(2024, 2, 29, 12, 0, tzinfo=PT)
    age = AgeBreakdown(4, 0, 0, 0, total_days=1461, total_hours=35064)
    assert detect(born, feb_29, age, birthday=True, milestones=()) == "Happy 4th Birthday!"


def test_milestone_hits_total_days():
    now = datetime(2025, 6, 9, 12, 0, tzinfo=PT)
    age = AgeBreakdown(2, 8, 28, 8, total_days=1000, total_hours=24008)
    assert detect(BORN, now, age, birthday=False, milestones=MILESTONES) == "1000 days!"


def test_milestone_singular():
    """The pluralize helper is used so 1 day reads as singular."""
    now = datetime(2022, 9, 13, 3, 47, tzinfo=PT)
    age = AgeBreakdown(0, 0, 1, 0, total_days=1, total_hours=24)
    assert detect(BORN, now, age, birthday=False, milestones=(1,)) == "1 day!"


def test_non_milestone_returns_none():
    now = datetime(2026, 4, 27, 7, 47, tzinfo=PT)
    assert detect(BORN, now, NORMAL, birthday=False, milestones=MILESTONES) is None


def test_birthday_takes_precedence_over_milestone():
    """If a milestone day collides with the actual birthday, birthday wins."""
    now = datetime(2026, 9, 12, 3, 47, tzinfo=PT)
    age = AgeBreakdown(4, 0, 0, 0, total_days=1000, total_hours=24000)
    assert detect(BORN, now, age, birthday=True, milestones=(1000,)) == "Happy 4th Birthday!"


def test_empty_milestones_disables_milestone_path():
    now = datetime(2025, 6, 9, 12, 0, tzinfo=PT)
    age = AgeBreakdown(2, 8, 28, 8, total_days=1000, total_hours=24008)
    assert detect(BORN, now, age, birthday=False, milestones=()) is None


def test_birthday_true_falls_through_to_milestone_on_non_birthday():
    """birthday=True doesn't block the milestone path on a non-birthday day —
    the kid still gets "1000 days!" on day 1000 if it doesn't fall on Sep 12.
    Existing tests pin this with birthday=False; this one closes the loop."""
    now = datetime(2025, 6, 9, 12, 0, tzinfo=PT)
    age = AgeBreakdown(2, 8, 28, 8, total_days=1000, total_hours=24008)
    assert detect(BORN, now, age, birthday=True, milestones=MILESTONES) == "1000 days!"


@pytest.mark.parametrize("n,expected", [
    (1, "1st"),
    (2, "2nd"),
    (3, "3rd"),
    (4, "4th"),
    (10, "10th"),
    (11, "11th"),
    (12, "12th"),
    (13, "13th"),
    (14, "14th"),
    (20, "20th"),
    (21, "21st"),
    (22, "22nd"),
    (23, "23rd"),
    (101, "101st"),
    (102, "102nd"),
    (103, "103rd"),
    (111, "111th"),
    (112, "112th"),
    (113, "113th"),
])
def test_ordinal_direct(n, expected):
    """The teens branch (11, 12, 13 → "th") is only reachable through
    realistic detect() inputs at age 11–13; pin the helper directly so the
    111/112/113 mod-100 logic is verified without waiting a century."""
    assert _ordinal(n) == expected
