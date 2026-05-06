import os
from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from kidage.__main__ import (
    VERSION_FILE_CANDIDATES,
    _default_config_path,
    _deployed_revision,
    _system_zone,
    _version_string,
    main,
)
from kidage.render import HEIGHT, WIDTH

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = REPO_ROOT / "config.example.toml"


def test_preview_writes_png_at_panel_size(tmp_path):
    out = tmp_path / "preview.png"
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(out),
        "--now", "2026-04-27T07:47:00-07:00",
    ])
    assert rc == 0
    assert out.exists()

    img = Image.open(out)
    assert img.size == (WIDTH, HEIGHT)
    assert img.mode == "RGB"


def test_preview_renders_three_inks(tmp_path):
    """Black ink, red ink, and white background must all appear."""
    out = tmp_path / "preview.png"
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(out),
        "--now", "2026-04-27T07:47:00-07:00",
    ])
    colors = {c for _, c in Image.open(out).getcolors(maxcolors=10)}
    assert (0, 0, 0) in colors
    assert (220, 30, 30) in colors
    assert (255, 255, 255) in colors


def test_preview_is_deterministic_for_pinned_now(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    args = [
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T07:47:00-07:00",
    ]
    main(args + ["--preview", str(a)])
    main(args + ["--preview", str(b)])
    assert a.read_bytes() == b.read_bytes()


def test_default_config_path_prefers_env(monkeypatch, tmp_path):
    target = tmp_path / "from-env.toml"
    monkeypatch.setenv("KIDAGE_CONFIG", str(target))
    assert _default_config_path() == target


def test_default_config_path_falls_back_to_local(monkeypatch, tmp_path):
    monkeypatch.delenv("KIDAGE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("")
    assert _default_config_path() == Path("config.toml")


def test_default_config_path_falls_back_to_etc(monkeypatch, tmp_path):
    monkeypatch.delenv("KIDAGE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _default_config_path() == Path("/etc/kidage/config.toml")


def test_main_invokes_display_when_no_preview(tmp_path, monkeypatch):
    """Without --preview, main() should hand the planes to display.show."""
    captured = {}

    def fake_show(black, red, today=None):
        captured["black"] = black
        captured["red"] = red
        captured["today"] = today

    import kidage.display
    monkeypatch.setattr(kidage.display, "show", fake_show)
    # __main__ does `from kidage.display import show` inside the function,
    # so patching the module attribute is enough.

    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T07:47:00-07:00",
    ])
    assert rc == 0
    assert captured["black"].size == (WIDTH, HEIGHT)
    assert captured["red"].size == (WIDTH, HEIGHT)
    assert captured["today"].isoformat() == "2026-04-27"


def _called_show(monkeypatch) -> list[tuple]:
    """Patch display.show with a recorder and return the call list."""
    calls: list[tuple] = []

    def fake_show(black, red, today=None):
        calls.append((black, red, today))

    import kidage.display
    monkeypatch.setattr(kidage.display, "show", fake_show)
    return calls


def test_main_skips_display_before_wake_hour(monkeypatch):
    calls = _called_show(monkeypatch)
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T06:59:00-07:00",
    ])
    assert rc == 0
    assert calls == []


def test_main_skips_display_after_sleep_hour(monkeypatch):
    calls = _called_show(monkeypatch)
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T22:00:00-07:00",
    ])
    assert rc == 0
    assert calls == []


def test_main_runs_at_wake_hour_inclusive(monkeypatch):
    calls = _called_show(monkeypatch)
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T07:00:00-07:00",
    ])
    assert rc == 0
    assert len(calls) == 1


def test_main_runs_at_sleep_hour_inclusive(monkeypatch):
    calls = _called_show(monkeypatch)
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--now", "2026-04-27T21:30:00-07:00",
    ])
    assert rc == 0
    assert len(calls) == 1


def test_main_preview_on_birthday_differs_from_normal_day(tmp_path):
    """End-to-end: a preview pinned to the kid's birthday must render a
    different image than a non-birthday preview, proving the special-day
    plumbing reaches render() through main()."""
    normal = tmp_path / "normal.png"
    bday = tmp_path / "bday.png"
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(normal),
        "--now", "2026-04-27T07:47:00-07:00",
    ])
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(bday),
        "--now", "2026-09-12T08:00:00-07:00",  # Lilah's birthday
    ])
    assert normal.read_bytes() != bday.read_bytes()


def test_system_zone_reads_localtime_symlink(tmp_path, monkeypatch):
    # Most distros ship /etc/localtime as a symlink into /usr/share/zoneinfo.
    fake_tzdata = tmp_path / "zoneinfo" / "America" / "Los_Angeles"
    fake_tzdata.parent.mkdir(parents=True)
    fake_tzdata.write_bytes(b"")
    fake_localtime = tmp_path / "localtime"
    os.symlink(fake_tzdata, fake_localtime)

    real_path = Path
    def fake_path(arg):
        if arg == "/etc/localtime":
            return fake_localtime
        if arg == "/etc/timezone":
            return tmp_path / "missing-timezone"
        return real_path(arg)
    monkeypatch.setattr("kidage.__main__.Path", fake_path)

    zone = _system_zone()
    assert isinstance(zone, ZoneInfo)
    assert str(zone) == "America/Los_Angeles"


def test_system_zone_falls_back_to_utc_when_nothing_configured(tmp_path, monkeypatch):
    # Belt-and-braces: a host with neither a /etc/localtime symlink nor an
    # /etc/timezone file shouldn't crash; UTC is a safe default.
    real_path = Path
    def fake_path(arg):
        if arg == "/etc/localtime":
            return tmp_path / "missing-localtime"
        if arg == "/etc/timezone":
            return tmp_path / "missing-timezone"
        return real_path(arg)
    monkeypatch.setattr("kidage.__main__.Path", fake_path)

    zone = _system_zone()
    assert isinstance(zone, ZoneInfo)
    assert str(zone) == "UTC"


def test_system_zone_falls_back_to_etc_timezone(tmp_path, monkeypatch):
    # Some Debian-likes write the IANA name to /etc/timezone instead of (or
    # alongside) the symlink.
    fake_timezone = tmp_path / "timezone"
    fake_timezone.write_text("America/New_York\n")

    real_path = Path
    def fake_path(arg):
        if arg == "/etc/localtime":
            return tmp_path / "missing-localtime"
        if arg == "/etc/timezone":
            return fake_timezone
        return real_path(arg)
    monkeypatch.setattr("kidage.__main__.Path", fake_path)

    zone = _system_zone()
    assert isinstance(zone, ZoneInfo)
    assert str(zone) == "America/New_York"


def test_live_now_carries_dst_aware_zoneinfo(tmp_path, monkeypatch):
    # End-to-end DST regression for the live path (no --now). born_at is
    # saved at fixed -08:00 (PST when the config was written); the system
    # is in America/Los_Angeles and "now" is in summer. With a fixed-offset
    # tzinfo on now, compute would project born_at into -07:00 and report
    # 23 hours on the monthly anniversary. With a ZoneInfo, it lands at 0.
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[kid]\n'
        'name = "Lily"\n'
        'born_at = 2024-03-09T13:54:00-08:00\n'
        '[schedule]\nwake_hour = 7\nsleep_hour = 21\n'
        '[display]\nflip = false\naccent = "heart"\nformat = "extended"\n'
        '[special_days]\nbirthday = true\nmilestones = []\n'
    )

    fake_tzdata = tmp_path / "zoneinfo" / "America" / "Los_Angeles"
    fake_tzdata.parent.mkdir(parents=True)
    fake_tzdata.write_bytes(b"")
    fake_localtime = tmp_path / "localtime"
    os.symlink(fake_tzdata, fake_localtime)
    real_path = Path
    def fake_path(arg):
        if arg == "/etc/localtime":
            return fake_localtime
        if arg == "/etc/timezone":
            return tmp_path / "missing"
        return real_path(arg)
    monkeypatch.setattr("kidage.__main__.Path", fake_path)

    # Pin datetime.now to a summer anniversary moment in PDT.
    from datetime import datetime as _dt

    class FakeDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 9, 13, 54, tzinfo=tz)
    monkeypatch.setattr("kidage.__main__.datetime", FakeDateTime)

    captured = {}
    real_compute = __import__("kidage.age", fromlist=["compute"]).compute
    def fake_compute(born_at, now):
        captured["now"] = now
        return real_compute(born_at, now)
    monkeypatch.setattr("kidage.__main__.compute", fake_compute)

    # Patch display.show so the live path doesn't try to touch hardware.
    import kidage.display
    monkeypatch.setattr(kidage.display, "show", lambda *_, **__: None)

    rc = main(["--config", str(cfg)])
    assert rc == 0
    now = captured["now"]
    assert isinstance(now.tzinfo, ZoneInfo)
    assert str(now.tzinfo) == "America/Los_Angeles"

    from kidage.age import compute
    age = compute(_dt.fromisoformat("2024-03-09T13:54:00-08:00"), now)
    assert (age.years, age.months, age.days, age.hours) == (2, 1, 0, 0)


def test_deployed_revision_returns_none_when_no_candidate_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kidage.__main__.VERSION_FILE_CANDIDATES", [tmp_path / "missing"]
    )
    assert _deployed_revision() is None


def test_deployed_revision_reads_first_existing_candidate(tmp_path, monkeypatch):
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    fallback.write_text("from-fallback\n")
    monkeypatch.setattr(
        "kidage.__main__.VERSION_FILE_CANDIDATES", [primary, fallback]
    )
    assert _deployed_revision() == "from-fallback"
    primary.write_text("from-primary\n")
    assert _deployed_revision() == "from-primary"


def test_deployed_revision_treats_empty_file_as_missing(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("   \n")
    monkeypatch.setattr("kidage.__main__.VERSION_FILE_CANDIDATES", [f])
    assert _deployed_revision() is None


def test_version_string_includes_package_version_without_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kidage.__main__.VERSION_FILE_CANDIDATES", [tmp_path / "missing"]
    )
    s = _version_string()
    assert s.startswith("kidage ")
    assert "(" not in s


def test_version_string_includes_revision_when_present(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("v0.1.0-3-gabc1234-dirty\n")
    monkeypatch.setattr("kidage.__main__.VERSION_FILE_CANDIDATES", [f])
    s = _version_string()
    assert "v0.1.0-3-gabc1234-dirty" in s
    assert s.startswith("kidage ")


def test_version_flag_prints_and_exits_zero(tmp_path, monkeypatch, capsys):
    f = tmp_path / "VERSION"
    f.write_text("v0.1.0-3-gabc1234-dirty\n")
    monkeypatch.setattr("kidage.__main__.VERSION_FILE_CANDIDATES", [f])
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "kidage" in out
    assert "v0.1.0-3-gabc1234-dirty" in out


def test_version_candidates_include_install_dir_path():
    # Regression guard: install.sh writes /opt/kidage/VERSION, but a
    # non-editable `pip install` puts kidage/__main__.py under
    # .venv/lib/.../site-packages, so a __file__-relative path alone won't
    # find it. The deployed install dir must stay in the candidate list.
    assert Path("/opt/kidage/VERSION") in VERSION_FILE_CANDIDATES


def test_preview_ignores_wake_window(tmp_path, monkeypatch):
    """--preview is for layout work and must render at any hour."""
    calls = _called_show(monkeypatch)
    out = tmp_path / "preview.png"
    rc = main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(out),
        "--now", "2026-04-27T03:00:00-07:00",
    ])
    assert rc == 0
    assert out.exists()
    assert calls == []  # preview path never touches display.show


def _after_hours_config(tmp_path: Path) -> Path:
    """Minimal config that opts in to after-hours inversion."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[kid]\n'
        'name = "Lily"\n'
        'born_at = 2022-09-12T03:47:00-07:00\n'
        '[schedule]\nwake_hour = 7\nsleep_hour = 21\n'
        '[display]\n'
        'after_hours_invert = true\n'
        '[location]\nlatitude = 37.2872\nlongitude = -121.95\n'
    )
    return cfg


def test_after_hours_preview_via_cli_flag_inverts(tmp_path, monkeypatch):
    """--after-hours forces inversion regardless of --now / sunset, so
    layout previews don't have to wait for dusk."""
    out_normal = tmp_path / "normal.png"
    out_after = tmp_path / "after.png"
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(out_normal),
        "--now", "2026-04-27T12:00:00-07:00",
    ])
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--after-hours",
        "--preview", str(out_after),
        "--now", "2026-04-27T12:00:00-07:00",
    ])
    assert out_normal.read_bytes() != out_after.read_bytes()


def test_live_after_hours_inverts_when_past_sunset(tmp_path, monkeypatch):
    """Live path: with after_hours_invert=true and lat/lon set, a refresh
    after sunset hands an inverted black plane to display.show."""
    cfg = _after_hours_config(tmp_path)

    # Pin sunset to a known wall-clock so the test is deterministic
    # regardless of the real solar position math.
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz
    fake_sunset = _dt(2026, 4, 28, 2, 30, tzinfo=UTC)  # 19:30 PDT
    fake_sunrise = _dt(2026, 4, 27, 13, 0, tzinfo=UTC)  # 06:00 PDT
    monkeypatch.setattr(
        "kidage.solar.sun_times",
        lambda d, lat, lon: (fake_sunrise, fake_sunset),
    )

    PT = _tz(_td(hours=-7))

    class FakeDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            # 20:00 PDT — past the fake sunset, still inside wake window.
            return _dt(2026, 4, 27, 20, 0, tzinfo=tz)
    monkeypatch.setattr("kidage.__main__.datetime", FakeDateTime)
    # _system_zone is called inside main; force it to a fixed-offset zone
    # the fake sunset can be compared against without DST surprises.
    monkeypatch.setattr("kidage.__main__._system_zone", lambda: PT)

    after_calls = _called_show(monkeypatch)
    rc = main(["--config", str(cfg)])
    assert rc == 0
    assert len(after_calls) == 1
    inverted_black = after_calls[0][0]

    # And again, but at a wall clock before sunset — should NOT invert.
    class PreSunsetDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 27, 12, 0, tzinfo=tz)  # noon PDT
    monkeypatch.setattr("kidage.__main__.datetime", PreSunsetDateTime)
    pre_calls = _called_show(monkeypatch)
    rc = main(["--config", str(cfg)])
    assert rc == 0
    assert len(pre_calls) == 1
    normal_black = pre_calls[0][0]

    assert inverted_black.tobytes() != normal_black.tobytes()


def test_quiet_preview_via_cli_flag_changes_render(tmp_path):
    """--quiet forces the quiet layout regardless of --now / sleep_hour, so
    layout previews don't have to wait until 21:00."""
    out_normal = tmp_path / "normal.png"
    out_quiet = tmp_path / "quiet.png"
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--preview", str(out_normal),
        "--now", "2026-04-27T12:00:00-07:00",
    ])
    main([
        "--config", str(EXAMPLE_CONFIG),
        "--quiet",
        "--preview", str(out_quiet),
        "--now", "2026-04-27T12:00:00-07:00",
    ])
    assert out_normal.read_bytes() != out_quiet.read_bytes()


def test_live_quiet_triggers_at_sleep_hour(tmp_path, monkeypatch):
    """Live path: a refresh at sleep_hour (21:00 in the example config) must
    render the quiet layout — different black plane than a refresh earlier
    in the day, since the sub line and full-mode totals are gone."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[kid]\n'
        'name = "Lily"\n'
        'born_at = 2022-09-12T03:47:00-07:00\n'
        '[schedule]\nwake_hour = 7\nsleep_hour = 21\n'
        '[display]\nformat = "full"\n'
    )

    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz
    PT = _tz(_td(hours=-7))
    monkeypatch.setattr("kidage.__main__._system_zone", lambda: PT)

    class NoonDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 27, 12, 0, tzinfo=tz)
    monkeypatch.setattr("kidage.__main__.datetime", NoonDateTime)
    noon_calls = _called_show(monkeypatch)
    assert main(["--config", str(cfg)]) == 0
    noon_black = noon_calls[0][0]

    class SleepDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 27, 21, 0, tzinfo=tz)
    monkeypatch.setattr("kidage.__main__.datetime", SleepDateTime)
    sleep_calls = _called_show(monkeypatch)
    assert main(["--config", str(cfg)]) == 0
    sleep_black = sleep_calls[0][0]

    assert noon_black.tobytes() != sleep_black.tobytes()


def test_live_quiet_does_not_trigger_before_sleep_hour(tmp_path, monkeypatch):
    """A refresh at sleep_hour-1 must NOT engage quiet mode — only the
    final hour does."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[kid]\n'
        'name = "Lily"\n'
        'born_at = 2022-09-12T03:47:00-07:00\n'
        '[schedule]\nwake_hour = 7\nsleep_hour = 21\n'
        '[display]\nformat = "full"\n'
    )

    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz
    PT = _tz(_td(hours=-7))
    monkeypatch.setattr("kidage.__main__._system_zone", lambda: PT)

    captured = {}
    real_render = __import__("kidage.render", fromlist=["render"]).render
    def fake_render(*args, **kwargs):
        captured["quiet"] = kwargs.get("quiet", False)
        return real_render(*args, **kwargs)
    monkeypatch.setattr("kidage.__main__.render", fake_render)

    class JustBeforeSleep(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 27, 20, 0, tzinfo=tz)
    monkeypatch.setattr("kidage.__main__.datetime", JustBeforeSleep)
    _called_show(monkeypatch)
    assert main(["--config", str(cfg)]) == 0
    assert captured["quiet"] is False


def test_live_after_hours_disabled_never_inverts(tmp_path, monkeypatch):
    """A config that omits after_hours_invert must never invert, even
    past sunset — and must skip the sunset calc entirely so a
    misconfigured location can't cause surprises."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[kid]\n'
        'name = "Lily"\n'
        'born_at = 2022-09-12T03:47:00-07:00\n'
        '[schedule]\nwake_hour = 7\nsleep_hour = 21\n'
    )

    PT = _tz(_td(hours=-7))

    class FakeDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            return _dt(2026, 4, 27, 20, 30, tzinfo=tz)  # past sunset
    monkeypatch.setattr("kidage.__main__.datetime", FakeDateTime)
    monkeypatch.setattr("kidage.__main__._system_zone", lambda: PT)

    # If after_hours_invert is off, sun_times must not be called.
    def boom(*args, **kwargs):
        raise AssertionError("sun_times called when after-hours is off")
    monkeypatch.setattr("kidage.solar.sun_times", boom)

    calls = _called_show(monkeypatch)
    rc = main(["--config", str(cfg)])
    assert rc == 0
    assert len(calls) == 1
