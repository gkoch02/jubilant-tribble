# BeanClock — kid age e-paper display

[![CI](https://github.com/gkoch02/BeanClock/actions/workflows/ci.yml/badge.svg)](https://github.com/gkoch02/BeanClock/actions/workflows/ci.yml)

A tiny appliance: a Raspberry Pi Zero 2 W driving a Waveshare 2.13"
black/white/red e-paper (V4) shows how old your kiddo is, broken down into
years / months / days / hours. It refreshes once an hour during waking hours
and rests overnight.

![preview — heart accent, extended format](docs/preview.png)

The `display.accent` and `display.format` knobs change the border trim and how
the age is spelled out. A spread:

| Star corners, total days | Balloon corners, total hours | Heart corners, full layout |
| --- | --- | --- |
| ![star accent, days format](docs/preview-star-days.png) | ![balloon accent, hours format](docs/preview-balloon-hours.png) | ![heart accent, full format](docs/preview-heart-full.png) |

| Moon corners | Sun corners | Flower corners |
| --- | --- | --- |
| ![moon accent](docs/preview-moon.png) | ![sun accent](docs/preview-sun.png) | ![flower accent](docs/preview-flower.png) |

## Features

- Beautiful, legible, playful layout — rounded **Fredoka** type, two-color
  accents (heart / star / balloon / moon / sun / flower), no fussy clipart.
- Hourly refresh during a configurable wake window (default 07:00–21:00 local
  time), driven by a `systemd` timer that fires every hour and a wake-window
  check in the script itself — edit `/etc/kidage/config.toml` to change the
  hours, no timer reload needed.
- Special-day takeovers: on the kid's birthday the hero row reads "Happy Nth
  Birthday!", and on configurable day-count milestones (default 100 / 500 /
  1000 / 2000 / 5000) it reads "N days!" — the standard "Y years M months"
  phrasing slides to the sub line.
- Single TOML config file for the kid's name, birth datetime+timezone, wake
  window, and accent glyph.
- **After-hours inversion** — after sunset (computed from your
  `latitude`/`longitude` using a built-in NOAA algorithm, no network or API
  key needed) the black plane inverts to white-on-black so the display reads
  more comfortably in a dark room; red accents stay red. Inversion only fires
  within the configured wake window — deep-night hours still skip the refresh
  entirely.
- Once-a-day full clear to suppress ghosting; the other ~14 daily refreshes
  go straight to `display()` for less flicker.
- **Quiet last refresh** — the refresh at `sleep_hour` (the last one before
  the overnight freeze) drops the volatile days/hours sub line and the
  `full`-mode totals, so the panel doesn't sit overnight showing yesterday's
  hour count.
- Pure-Python, vendored Waveshare driver — no apt-time setup beyond Pillow's
  runtime libs.

## Bill of materials

| # | Part | Qty | Notes |
| - | ---- | --- | ----- |
| 1 | Raspberry Pi Zero 2 W | 1 | Any 64-bit Pi running Raspberry Pi OS Bookworm works; the Zero 2 W is the cheapest fit and the form factor the case/stand are sized for. |
| 2 | Waveshare 2.13" e-Paper HAT, **B/W/R, V4** (250×122) | 1 | Three-colour panel + driver board in one. The 40-pin female header drops straight onto the Pi's GPIO — no soldering, no jumpers. Make sure it's the **V4** revision; earlier revs use a different controller and the vendored driver won't talk to them. |
| 3 | microSD card, 8 GB or larger (Class 10 / A1) | 1 | Pi OS Lite (Bookworm or newer). 8 GB is plenty; the appliance writes almost nothing to disk. |
| 4 | USB micro-B power supply, 5 V / ≥ 2 A | 1 | The official Pi Zero supply is fine. The Zero 2 W uses **micro-B**, not USB-C. |
| 5 | Case / stand (optional) | 1 | Anything that exposes the panel and lets the 40-pin header seat fully on the Pi. |

SPI must be enabled on the Pi — `scripts/install.sh` does that for you
(`sudo raspi-config` → Interface Options → SPI if you'd rather do it by
hand). No other apt packages or HATs are required.

## Quick start

On a fresh Pi OS Lite SD card:

```bash
git clone https://github.com/gkoch02/BeanClock.git
cd BeanClock
sudo timedatectl set-timezone America/Los_Angeles  # use your tz (zoneinfo, not an offset)
sudo bash scripts/install.sh
sudo $EDITOR /etc/kidage/config.toml         # set name + birth datetime
sudo systemctl start kidage.service          # first refresh now
systemctl list-timers kidage.timer           # confirm next hourly fire
```

`wake_hour` and `sleep_hour` are interpreted against the Pi's system
timezone, so it must be a real zoneinfo (e.g. `America/Los_Angeles`) for
the wake window to track DST correctly.

The installer creates `kidage` system user, builds a virtualenv at
`/opt/kidage/.venv`, copies the `systemd` units, enables SPI, and starts the
timer.

## Configuration

`config.example.toml`:

```toml
[kid]
name = "Lilah"
# Local wall-clock time of birth, with timezone offset.
born_at = 2022-09-12T03:47:00-07:00

[schedule]
wake_hour  = 7    # inclusive, local time of first daily update
sleep_hour = 21   # inclusive, local time of last daily update

[display]
flip               = false      # rotate 180° if the ribbon comes out the other side
accent             = "heart"    # heart | star | balloon | moon | sun | flower
format             = "extended" # extended (years/months + days/hours) | days | hours | full
after_hours_invert = true       # invert to white-on-black after sunset (requires [location])

[location]
# Decimal degrees — used to compute today's sunset for after_hours_invert.
# Omit this whole block (and set after_hours_invert = false) to disable.
latitude  = 37.2872
longitude = -121.9500

[special_days]
birthday   = true                          # hero swaps to "Happy Nth Birthday!"
milestones = [100, 500, 1000, 2000, 5000]  # hero swaps to "N days!"; [] disables
```

When `after_hours_invert = true` the panel switches to white-on-black after
today's local sunset, computed on-device from `latitude`/`longitude` (NOAA
algorithm, no network needed). Red beads and accents remain red. The inversion
only fires within the `[wake_hour, sleep_hour]` window; deep-night hours still
skip the refresh entirely.

On a matching day the hero row is replaced and the standard age phrasing
slides to the sub line, regardless of `display.format`. Feb 29 births
celebrate Feb 28 in non-leap years; if a milestone happens to fall on the
birthday, the birthday wins.

The `born_at` offset pins the absolute moment of birth, but the
years/months/days/hours breakdown is computed against the Pi's system
zoneinfo, so the daily flip stays on the same wall-clock minute across
DST transitions. If the Pi moves zones the actual instant of birth is
preserved and its projection follows along — a Pacific-born kid on an
Eastern Pi sees the day flip three hours later in local time, not at the
old Pacific minute.

Edit `/etc/kidage/config.toml` and run `sudo systemctl start kidage.service`
to push the change to the panel immediately (the manual refresh still
respects `wake_hour`/`sleep_hour`, so widen those first if you're testing
outside waking hours). The next scheduled refresh will also pick up the
change.

## Development without hardware

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

pytest                                       # full suite is hardware-free
python -m kidage --config config.example.toml --preview /tmp/p.png
xdg-open /tmp/p.png                          # eyeball the layout
```

`--now 2026-04-27T07:00:00-07:00` lets you simulate any moment without
touching the system clock. `--after-hours` forces the inverted
(white-on-black) look for layout work without waiting for sunset; combine
both flags for deterministic screenshots of the night-mode layout.

## Repo layout

```
kidage/                       # package
  age.py                      # AgeBreakdown + dateutil-based compute()
  config.py                   # TOML loader + validation
  render.py                   # Pillow → (black plane, red plane)
  display.py                  # thin wrapper around the vendored driver
  special.py                  # birthday + milestone detection
  fonts/Fredoka.ttf           # SIL OFL variable font (shipped with the wheel)
  __main__.py                 # entrypoint: load → render → display | --preview
vendor/waveshare_epd/         # vendored from waveshareteam/e-Paper
systemd/kidage.{service,timer}
scripts/install.sh            # idempotent installer
tests/                        # pure-Python (no panel)
```

## Troubleshooting

- **`journalctl -u kidage.service` shows `RuntimeError: Failed to add edge
  detection`** — SPI is not enabled or the user is not in the `spi`/`gpio`
  groups. Re-run the installer.
- **Display is upside down** — set `flip = true` in `config.toml`.
- **Ghosting** — the daily clear at the first wake-hour fire wipes residual
  burn-in. Force one with `sudo rm /var/lib/kidage/last-clear && sudo
  systemctl start kidage.service`.
- **Wake window fires an hour late after a DST change** — the Pi's system
  timezone is set to a fixed offset (e.g. `Etc/GMT+7`) instead of a
  zoneinfo. Run `timedatectl status` to check, then
  `sudo timedatectl set-timezone America/Los_Angeles` (or your IANA zone)
  so the OS handles DST.
- **What's running on this Pi?** — `kidage --version` prints the package
  version plus the git revision recorded by `install.sh` (e.g.
  `kidage 0.1.0 (v0.1.0-3-gabc1234-dirty)`). The installer writes this to
  `/opt/kidage/VERSION` on every run, so re-running it after a `git pull`
  is enough to refresh the stamp.

## Licenses

- `kidage/`, `tests/`, `scripts/`, `systemd/` — MIT (see `LICENSE`).
- `vendor/waveshare_epd/` — MIT, © Waveshare.
- `kidage/fonts/Fredoka.ttf` — SIL Open Font License 1.1, see `kidage/fonts/OFL.txt`.
