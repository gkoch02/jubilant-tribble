# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Raspberry Pi Zero W 2 appliance that renders a kid's age (years / months /
days / hours) onto a Waveshare 2.13" b/w/r e-paper (V4, 250×122). A `systemd`
timer fires `python -m kidage` every hour from 07:00–21:00; each run is a
oneshot that loads the TOML config, computes the age, paints two PIL bitmaps
(one per ink plane), pushes them to the panel, puts the panel to sleep, and
exits. There is no daemon.

## Common commands

```bash
# Dev environment (laptop, no panel needed)
pip install -e '.[dev]'

# All tests — entire suite is hardware-free
pytest

# One test file / one test
pytest tests/test_render.py
pytest tests/test_age.py::test_leap_day_birth -v

# Render a PNG preview of the current layout without touching hardware
python -m kidage --config config.example.toml --preview /tmp/p.png
# Pin the wall clock for deterministic previews (e.g. while tweaking layout)
python -m kidage --config config.example.toml --preview /tmp/p.png \
    --now 2026-04-27T07:47:00-07:00

# On the Pi: install the appliance (idempotent)
sudo bash scripts/install.sh
# Force a refresh now (also exercises the real driver path)
sudo systemctl start kidage.service
journalctl -u kidage.service -f
```

## Architecture

`kidage/__main__.py` is the only entrypoint. It loads `kidage.config` →
calls `kidage.age.compute` → calls `kidage.special.detect` → calls
`kidage.render.render` → either writes a PNG (`--preview`) or calls
`kidage.display.show`. The split exists so the render path is hardware-free
and exercised by tests, while `display.py` isolates the `RPi.GPIO` /
`spidev` blast radius.

**Image planes (the easy thing to get wrong).** `render()` returns two PIL
images, both mode `"1"`, both at the panel's native 250×122. In each plane
the pixel value `0` means "ink here" and `1` means "leave alone" — *the same
convention applies to both the black and red planes*. To draw red, paint
black (`fill=0`) on the red plane. The vendored Waveshare driver ORs the
two planes onto the panel.

**Lazy hardware import.** `kidage.display.show` does `from
vendor.waveshare_epd import epd2in13b_V4` *inside* the function so importing
`kidage.render` (and running the test suite) on a non-Pi machine doesn't
require `RPi.GPIO`/`spidev`. Don't move that import to module scope.

**Once-a-day clear.** `display.show` consults `/var/lib/kidage/last-clear`
and only calls `epd.Clear()` on the first refresh of a given local date.
The other ~14 hourly refreshes go straight to `epd.display()`, which avoids
the tri-color panel's full inversion flicker. To force a clear on the next
run, delete that file. The state directory is overridable via
`KIDAGE_STATE_DIR` (the `systemd` unit sets it via `StateDirectory=kidage`).

**Variable font.** `kidage/fonts/Fredoka.ttf` is a single variable TTF with weight
and width axes. `render._font(size, weight)` calls
`set_variation_by_name(weight)` (`Light` / `Regular` / `Medium` / `SemiBold`
/ `Bold`); always go through this helper rather than constructing
`ImageFont.truetype` directly, otherwise text measurements at the same
nominal size will silently disagree with the rendered output.

**Frame is part of the layout contract.** `render._draw_frame` paints an
outer rounded black hairline plus red bead trim plus a corner glyph in
each corner. The constants `FRAME_OUTER`, `FRAME_BEAD_INSET`, and
`FRAME_PAD` define the keep-out region for text — header `y = FRAME_PAD`
and footer `y = HEIGHT - FRAME_PAD - 13` reference it directly. Resizing
text or moving the frame in isolation will produce clipping; adjust both.

**Per-theme tweaks.** The `accent` config (`heart` / `star` / `balloon` /
`moon` / `sun` / `flower`) controls the glyphs flanking the name row, the
corner glyphs, and whether the footer gets an accent. The heart theme
intentionally uses plain red dots in the frame corners (not small hearts)
and omits the footer accent — small hearts lost their shape at 4 px and
the row reads cleaner without one. See the `accent == "heart"` branches
in `_draw_frame` and `render`. `VALID_ACCENTS` in `kidage/config.py` is
the source of truth; keep `_draw_frame`, the name-row branches in
`render`, and the README spread in lockstep when adding a new glyph.

**Hero layout depends on `age_format`.** The `format` config knob
(`extended` / `days` / `hours` / `full`) reaches `render()` as
`age_format` and picks between two hero baselines: `HERO_Y_TWO_LINE = 33`
for `extended` and `full` (years/months hero with a days/hours sub line
at `y=68`) and `HERO_Y_ONE_LINE = 47` for the single-total `days` /
`hours` modes (centered vertically for the 28pt hero). `full` is
identical to `extended` except it also paints compact `total_days` /
`total_hours` readouts (e.g. `1324d` / `31780h`) on the black plane in
the bottom-left and bottom-right corners, sharing the footer row with
the centered red "since …" string. The hero font auto-shrinks in 2pt
steps down to 16pt if the string would overflow `WIDTH - 28`; preserve
that shrink loop when changing strings, since "31756 hours" already
lands near the limit.

**After-hours inversion.** When `display.after_hours_invert = true` and
`[location]` lat/long are set, `__main__` calls `kidage.solar.sun_times()`
on the live wall-clock date and passes `after_hours = now >= sunset` into
`render()`. `render()` swaps the black plane (0 ↔ 1) so the panel reads
white-on-black, **then punches black back out wherever the red plane has
ink** — the Waveshare driver ORs the two planes onto the panel, so a
uniformly-black plane would otherwise mask out every red bead/accent. The
wake-window skip at the top of `__main__` is unchanged: after-hours
operates inside `[wake_hour, sleep_hour]`, so deep-night hours still skip
the refresh entirely. `--now` previews stay literal (no surprise
inversion); pass `--after-hours` to force the inverted look for layout
work.

**Quiet mode at sleep_hour.** The systemd timer's last refresh of the day
lands at `cfg.sleep_hour`; after that the panel freezes overnight on
whatever was last painted, so volatile metrics (days/hours sub line,
`full`-mode `total_days`/`total_hours` corners) would show stale numbers
until morning. `__main__` sets `quiet = (now.hour == cfg.sleep_hour)` on
the live path and threads it into `render()`, which forces the hero to
`_hero_line(age)` (years/months) at `HERO_Y_TWO_LINE` and skips the sub
line and `full` corners. Frame, header, and the static "since …" footer
stay. Quiet wins over both `special` (a 21:00 birthday/milestone is
suppressed) and `age_format` (a `days` / `hours` config falls back to
years/months for the freeze). `--now` previews stay literal; pass
`--quiet` to force the layout for design work.

**Special-day mode is a third axis on top of `age_format`.**
`kidage.special.detect()` returns a hero override string when `now` falls
on the kid's birthday (matching `born_at.month`/`day`, with Feb 29 → Feb
28 fallback in non-leap years) or when `age.total_days` is in the
configured milestones. `__main__` passes the result to `render()` as the
`special` keyword. When set, `render()` ignores `age_format` for the hero
row, uses `HERO_Y_TWO_LINE`, and forces the sub line to `_hero_line(age)`
("Y years M months") regardless of format — so a milestone hit in
`format = "days"` doesn't render "1000 days!" over "1000 days". Birthday
wins over milestone on overlap; both are toggleable via `[special_days]`
in the config. The same hero shrink loop applies, so long labels like
"Happy 99th Birthday!" don't need special handling.

**Age math is wall-clock, not elapsed-UTC.** `kidage.age.compute` projects
both `born_at` and `now` into `now.tzinfo` and strips the tzinfo before
handing them to `relativedelta` and the timedelta. Without that step, a
born_at saved at `-08:00` (PST) and a `now` of `-07:00` (PDT) would diff
through real elapsed time and report `17 days 23 hours` at 1:54pm on a
monthly anniversary instead of `18 days 0 hours` — same DST trap as the
wake-window note below. A consequence: `total_days`/`total_hours` are
also wall-clock counts, so spring-forward "loses" an hour and fall-back
"gains" one; that's intentional and keeps the totals consistent with the
years/months/days line above. If the family moves zones, the actual
instant of birth is preserved but its wall-clock projection follows the
system zoneinfo (Pacific birth → Eastern Pi means the daily flip moves
to 4:54pm ET).

## Configuration

`config.example.toml` is the canonical schema. The installer copies it to
`/etc/kidage/config.toml` (`Environment=KIDAGE_CONFIG=…` in the unit). The
TOML loader rejects naïve datetimes — `kid.born_at` must include an offset
(e.g. `2022-09-12T03:47:00-07:00`); the offset pins the absolute moment of
birth, but wall-clock semantics for the anniversary follow the Pi's system
zoneinfo (see "Age math is wall-clock" above). The `[display]` block is
strict: unknown keys raise at load time so a typo like `layout = "full"`
fails fast instead of silently rendering the default — keep the
allow-list (`flip` / `accent` / `format` / `after_hours_invert`) in sync
with the dataclass when adding a knob. The `[location]` block is also
strict (`latitude` / `longitude` only) and is required when
`after_hours_invert = true`.

## Deployed-revision stamping

`scripts/install.sh` writes `git describe --always --dirty --tags` to
`/opt/kidage/VERSION` after the rsync (must run *after*, since
`rsync --delete` would otherwise wipe the file the installer just wrote on
re-runs). `kidage --version` reads that file via
`VERSION_FILE_CANDIDATES` in `__main__.py` and prints
`kidage <pkg> (<rev>)`. The candidate list is order-sensitive:
`/opt/kidage/VERSION` is checked first because the installer does
`pip install $INSTALL_DIR[pi]` — a *non-editable* install — so
`Path(__file__).parent.parent` resolves to the venv's site-packages, not
the install root. The `__file__`-relative path stays in the list as the
editable-dev fallback (`pip install -e .`). Don't reorder or drop either
entry without updating `tests/test_main.py`, which pins the production
path.

## Scheduling

`systemd/kidage.timer` fires every hour, all day (`OnCalendar=*-*-*
*:00:00`). The wake-window enforcement lives in `kidage.__main__`: it
compares `now.hour` to `cfg.wake_hour`/`cfg.sleep_hour` (both inclusive)
and exits 0 without touching the panel when outside the window. This
keeps `/etc/kidage/config.toml` as the single source of truth for the
schedule — editing the timer is no longer required to change waking
hours. `--preview` deliberately bypasses the window so layout work works
at any hour.

**`now.tzinfo` must be a `ZoneInfo`, not a fixed offset.** The TOML
offset on `cfg.born_at` is whatever was in effect at birth (e.g.
`-08:00` for a winter Pacific birth), which is a fixed offset. So is the
result of `datetime.now().astimezone()` — Python returns a
`datetime.timezone` for the *current* moment, not a zoneinfo. Either
one, fed to `age.compute`, makes `born_at.astimezone(now.tzinfo)`
incapable of replaying DST history: a winter-saved birth lands in a
summer offset and the anniversary slips an hour. The entrypoint resolves
the IANA name from `/etc/localtime` (or `/etc/timezone`) via
`_system_zone()` and builds `now` with `datetime.now(tz=…)` so the Pi's
zoneinfo (set via `timedatectl set-timezone`) drives wall-clock
semantics; don't "simplify" that back to `astimezone()` or
`tz=cfg.born_at.tzinfo`. `--now` is exempt — it preserves the caller's
ISO offset so layout previews show the exact wall clock requested.

`Persistent=true` means a Pi that boots mid-day catches up exactly once
instead of waiting for the next top of the hour; keep that flag or
hourly catch-up regressions become hard to spot. `AccuracySec=1min` lets
`systemd` batch with other timers, which matters on a Zero 2 because
waking SPI takes a non-trivial fraction of a watt — so does spawning
Python every hour for the no-op slots, but the cost is dwarfed by the
SPI-active hours and the simpler "edit one TOML file" UX wins.

## Vendored code

`vendor/waveshare_epd/` is a verbatim copy of `epd2in13b_V4.py` and
`epdconfig.py` from `waveshareteam/e-Paper`. Don't edit these files; if a
fix is needed, wrap it in `kidage/display.py`.

## Adding tests

Tests live under `tests/`. Render-side tests import `kidage.render`
directly, which is hardware-free. `tests/test_display.py` does import
`kidage.display`, but only after stubbing `vendor.waveshare_epd` in
`sys.modules` — the lazy `from vendor.waveshare_epd import epd2in13b_V4`
inside `show()` then resolves to the stub, so `RPi.GPIO` / `spidev` are
never loaded. Reuse the `monkeypatch.setitem(sys.modules, …)` fixture in
that file if you need to exercise `display.show` again.

Use `compose_preview(black, red)` to get an RGB image, or check
`image.tobytes()` for inked pixels — `Image.getdata()` is deprecated in
Pillow 14.
