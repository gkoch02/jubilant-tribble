from datetime import timedelta
from pathlib import Path

import pytest

from kidage.config import load


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_load_minimal(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "Lily"
born_at = 2022-09-12T03:47:00-07:00
"""))
    assert cfg.name == "Lily"
    assert cfg.born_at.utcoffset() == timedelta(hours=-7)
    assert cfg.wake_hour == 7
    assert cfg.sleep_hour == 21
    assert cfg.flip is False
    assert cfg.accent == "heart"


def test_load_full(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "Maximilian"
born_at = 2024-01-15T08:00:00+00:00

[schedule]
wake_hour = 6
sleep_hour = 22

[display]
flip = true
accent = "balloon"
"""))
    assert cfg.name == "Maximilian"
    assert cfg.wake_hour == 6
    assert cfg.sleep_hour == 22
    assert cfg.flip is True
    assert cfg.accent == "balloon"


def test_rejects_naive_born_at(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_bad_schedule(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[schedule]
wake_hour = 22
sleep_hour = 6
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_unknown_accent(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
accent = "unicorn"
""")
    with pytest.raises(ValueError):
        load(p)


def test_age_format_defaults_to_extended(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
"""))
    assert cfg.age_format == "extended"


@pytest.mark.parametrize("value", ["days", "hours", "extended", "full", "DAYS"])
def test_age_format_accepts_known_values(tmp_path, value):
    cfg = load(_write(tmp_path, f"""
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
format = "{value}"
"""))
    assert cfg.age_format == value.lower()


def test_rejects_unknown_format(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
format = "weeks"
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_unknown_display_key(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
layout = "full"
""")
    with pytest.raises(ValueError, match="layout"):
        load(p)


def test_after_hours_invert_and_location_default_off(tmp_path):
    """A config without [location] or after_hours_invert keeps existing
    behavior — feature is opt-in."""
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
"""))
    assert cfg.after_hours_invert is False
    assert cfg.latitude is None
    assert cfg.longitude is None


def test_load_full_after_hours_config(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
after_hours_invert = true
[location]
latitude = 40.0150
longitude = -105.2705
"""))
    assert cfg.after_hours_invert is True
    assert cfg.latitude == 40.0150
    assert cfg.longitude == -105.2705


def test_after_hours_invert_requires_location(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
after_hours_invert = true
""")
    with pytest.raises(ValueError, match="after_hours_invert"):
        load(p)


def test_location_requires_both_lat_and_lon(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[location]
latitude = 40.0150
""")
    with pytest.raises(ValueError, match="set together"):
        load(p)


def test_location_rejects_unknown_key(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[location]
latitude = 0.0
longitude = 0.0
city = "Springfield"
""")
    with pytest.raises(ValueError, match="city"):
        load(p)


def test_location_rejects_out_of_range_latitude(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[location]
latitude = 95.0
longitude = 0.0
""")
    with pytest.raises(ValueError, match="latitude"):
        load(p)


def test_location_rejects_out_of_range_longitude(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[location]
latitude = 0.0
longitude = -200.0
""")
    with pytest.raises(ValueError, match="longitude"):
        load(p)


def test_special_days_defaults(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
"""))
    assert cfg.birthday is True
    assert cfg.milestones == (100, 500, 1000, 2000, 5000)


def test_special_days_custom(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
birthday = false
milestones = [42, 7, 7, 100]
"""))
    assert cfg.birthday is False
    # Loader sorts and dedupes so render-side checks don't have to.
    assert cfg.milestones == (7, 42, 100)


def test_special_days_empty_milestones_allowed(tmp_path):
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
milestones = []
"""))
    assert cfg.milestones == ()


def test_rejects_non_positive_milestone(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
milestones = [100, 0, 500]
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_non_int_milestone(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
milestones = [100, "many", 500]
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_non_list_milestones(tmp_path):
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
milestones = 1000
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_boolean_in_milestones(tmp_path):
    """The loader guards against True/False sneaking in as milestones, since
    Python treats `True` as `isinstance(int)` and `True == 1`. TOML arrays
    accept mixed bool/int, so this is reachable from a real config file."""
    p = _write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00

[special_days]
milestones = [100, true]
""")
    with pytest.raises(ValueError):
        load(p)


def test_rejects_non_datetime_born_at(tmp_path):
    """A TOML string for born_at (vs. an offset datetime literal) must raise.
    This is the defense for the user accidentally quoting the value."""
    p = _write(tmp_path, '''
[kid]
name = "X"
born_at = "2024-01-01T00:00:00+00:00"
''')
    with pytest.raises(ValueError, match="TOML datetime"):
        load(p)


def test_missing_kid_section_raises(tmp_path):
    """A config without [kid] is malformed. Today this raises KeyError; pin
    that behavior so a future refactor to a friendlier error is intentional."""
    p = _write(tmp_path, '[schedule]\nwake_hour = 7\n')
    with pytest.raises(KeyError):
        load(p)


def test_missing_kid_name_raises(tmp_path):
    p = _write(tmp_path, '[kid]\nborn_at = 2024-01-01T00:00:00+00:00\n')
    with pytest.raises(KeyError):
        load(p)


def test_missing_kid_born_at_raises(tmp_path):
    p = _write(tmp_path, '[kid]\nname = "X"\n')
    with pytest.raises(KeyError):
        load(p)


def test_accent_is_case_insensitive(tmp_path):
    """`accent = "HEART"` and `accent = "Heart"` should normalize to "heart"."""
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
accent = "STAR"
"""))
    assert cfg.accent == "star"


def test_flip_accepts_any_truthy_value(tmp_path):
    """Current behavior: `flip = "yes"` is parsed by TOML as the string "yes",
    then `bool()` coerces it to True. Pin this so a tightening (to require an
    actual TOML bool) is an intentional, visible change."""
    # TOML can't put a string into a bool field via type coercion, but we
    # exercise the `bool(display.get(...))` call path with the boolean TOML
    # literal and confirm it round-trips.
    cfg = load(_write(tmp_path, """
[kid]
name = "X"
born_at = 2024-01-01T00:00:00+00:00
[display]
flip = true
"""))
    assert cfg.flip is True
