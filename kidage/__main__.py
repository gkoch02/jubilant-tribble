from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path
from zoneinfo import ZoneInfo

from kidage.age import compute
from kidage.config import load
from kidage.render import compose_preview, render
from kidage.special import detect as detect_special

log = logging.getLogger("kidage")

# scripts/install.sh writes `git describe --always --dirty --tags` to
# /opt/kidage/VERSION (the install dir, also hardcoded in systemd/kidage.service
# and install.sh). The __file__-relative path is the editable-install fallback
# for `pip install -e .` dev work — under a non-editable install (which the
# installer uses) __file__ lives in site-packages, not the install root.
VERSION_FILE_CANDIDATES = [
    Path("/opt/kidage/VERSION"),
    Path(__file__).resolve().parent.parent / "VERSION",
]


def _default_config_path() -> Path:
    env = os.environ.get("KIDAGE_CONFIG")
    if env:
        return Path(env)
    local = Path("config.toml")
    if local.exists():
        return local
    return Path("/etc/kidage/config.toml")


def _deployed_revision() -> str | None:
    """Return the git revision recorded by install.sh, or None if absent."""
    for path in VERSION_FILE_CANDIDATES:
        if path.is_file():
            return path.read_text().strip() or None
    return None


def _version_string() -> str:
    try:
        pkg = metadata.version("kidage")
    except metadata.PackageNotFoundError:
        pkg = "unknown"
    rev = _deployed_revision()
    return f"kidage {pkg} ({rev})" if rev else f"kidage {pkg}"


def _system_zone() -> ZoneInfo:
    # age.compute needs a DST-aware tzinfo to project born_at correctly across
    # DST boundaries. datetime.now().astimezone() yields a fixed-offset
    # datetime.timezone for the *current* moment, which can't replay a winter
    # birth's offset in summer — so resolve the IANA name from the OS instead.
    # Pi OS ships /etc/localtime as a symlink and /etc/timezone as a one-line
    # IANA name; if a future host ever ships /etc/localtime as a *copy* of the
    # tzdata blob with no /etc/timezone next to it, this falls back to UTC.
    p = Path("/etc/localtime")
    if p.is_symlink():
        target = os.readlink(p)
        marker = "zoneinfo/"
        idx = target.rfind(marker)
        if idx >= 0:
            return ZoneInfo(target[idx + len(marker):])
    tz_file = Path("/etc/timezone")
    if tz_file.exists():
        return ZoneInfo(tz_file.read_text().strip())
    return ZoneInfo("UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kidage", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to TOML config (env: KIDAGE_CONFIG; "
            "default: ./config.toml or /etc/kidage/config.toml)."
        ),
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Skip the e-paper and write a PNG preview to this path instead.",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="Override the current time (ISO 8601 with offset). Useful for previews.",
    )
    parser.add_argument(
        "--after-hours",
        action="store_true",
        help=(
            "Force the after-hours (inverted black/white, red preserved) look. "
            "Bypasses the sunset check; intended for layout previews."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=(
            "Force the quiet-hours layout (years/months only — hides volatile "
            "metrics that would go stale while the panel is frozen overnight). "
            "Bypasses the sleep_hour check; intended for layout previews."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=_version_string())
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load(args.config or _default_config_path())
    # The live path needs a DST-aware ZoneInfo (not the fixed-offset tzinfo
    # from `datetime.now().astimezone()`); otherwise age.compute can't project
    # a winter-saved born_at into a summer wall clock and the anniversary
    # slips an hour. --now keeps the caller's offset so layout previews show
    # the exact wall clock requested.
    now = (
        datetime.fromisoformat(args.now)
        if args.now
        else datetime.now(tz=_system_zone())
    )

    # The systemd timer fires hourly all day, so the wake/sleep window in
    # config is what actually decides which hours touch the panel. --preview
    # bypasses the window so layout work doesn't depend on wall-clock time.
    if args.preview is None and not (cfg.wake_hour <= now.hour <= cfg.sleep_hour):
        log.info(
            "now=%s hour=%d outside wake window [%d, %d]; skipping refresh",
            now.isoformat(), now.hour, cfg.wake_hour, cfg.sleep_hour,
        )
        return 0

    # Last refresh before quiet hours: the panel freezes on this image until
    # the next morning, so suppress volatile metrics. Live path only —
    # previews stay literal unless --quiet is passed.
    quiet = args.quiet
    if not quiet and args.now is None:
        quiet = now.hour == cfg.sleep_hour
        if quiet:
            log.info("quiet mode: last refresh before sleep_hour=%d", cfg.sleep_hour)

    after_hours = args.after_hours
    if not after_hours and cfg.after_hours_invert and args.now is None:
        # Live path only: compare wall-clock now to today's sunset at the
        # configured location. --now previews stay literal (no surprise
        # inversion) — use --after-hours to force the inverted look.
        # config.load() guarantees lat/lon are set when after_hours_invert
        # is true, so the asserts here are static-check belt-and-braces.
        from kidage.solar import sun_times
        assert cfg.latitude is not None
        assert cfg.longitude is not None
        times = sun_times(now.date(), cfg.latitude, cfg.longitude)
        if times is not None:
            sunset_local = times[1].astimezone(now.tzinfo)
            after_hours = now >= sunset_local
            log.info(
                "sunset=%s after_hours=%s",
                sunset_local.isoformat(), after_hours,
            )

    age = compute(cfg.born_at, now)
    log.info("kid=%s age=%s", cfg.name, age)

    special = detect_special(
        cfg.born_at,
        now,
        age,
        birthday=cfg.birthday,
        milestones=cfg.milestones,
    )
    if special is not None:
        log.info("special-day display: %r", special)

    black, red = render(
        cfg.name,
        age,
        cfg.born_at,
        accent=cfg.accent,
        flip=cfg.flip,
        age_format=cfg.age_format,
        special=special,
        after_hours=after_hours,
        quiet=quiet,
    )

    if args.preview is not None:
        compose_preview(black, red).save(args.preview)
        log.info("wrote preview to %s", args.preview)
        return 0

    from kidage.display import show
    show(black, red, today=now.date())
    return 0


if __name__ == "__main__":
    sys.exit(main())
