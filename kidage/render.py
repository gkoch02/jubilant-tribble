from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont

from kidage.age import AgeBreakdown, pluralize


class AccentFn(Protocol):
    def __call__(
        self,
        draw: ImageDraw.ImageDraw,
        cx: int,
        cy: int,
        size: int = ...,
    ) -> None: ...

WIDTH = 250
HEIGHT = 122

FONT_PATH = Path(__file__).resolve().parent / "fonts" / "Fredoka.ttf"


def _font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size=size)
    f.set_variation_by_name(weight)  # type: ignore[no-untyped-call]
    return f


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    w = _text_width(draw, text, font)
    draw.text(((WIDTH - w) // 2, y), text, font=font, fill=0)


def _hero_line(age: AgeBreakdown) -> str:
    if age.years == 0:
        return pluralize(age.months, "month") if age.months else "newborn"
    return f"{pluralize(age.years, 'year')}  {pluralize(age.months, 'month')}"


def _sub_line(age: AgeBreakdown) -> str:
    return f"{pluralize(age.days, 'day')}  ·  {pluralize(age.hours, 'hour')}"


def _draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 9) -> None:
    r = size // 2
    draw.ellipse((cx - size + 1, cy - r, cx, cy + r - 1), fill=0)
    draw.ellipse((cx, cy - r, cx + size - 1, cy + r - 1), fill=0)
    draw.polygon(
        [(cx - size + 1, cy), (cx + size - 1, cy), (cx, cy + size)],
        fill=0,
    )


def _draw_star(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 8) -> None:
    import math

    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = size if i % 2 == 0 else size * 0.45
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    draw.polygon(points, fill=0)


def _draw_balloon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 10) -> None:
    draw.ellipse((cx - size, cy - size, cx + size, cy + size - 2), fill=0)
    draw.polygon(
        [(cx - 2, cy + size - 3), (cx + 2, cy + size - 3), (cx, cy + size + 1)],
        fill=0,
    )
    draw.line((cx, cy + size + 1, cx, cy + size + 5), fill=0, width=1)


def _draw_moon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 8) -> None:
    r = size
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    # Bite a white disc out of the right side to leave a left-facing crescent.
    bite = max(2, r // 2 + 1)
    draw.ellipse((cx - r + bite, cy - r, cx + r + bite, cy + r), fill=1)


def _draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 8) -> None:
    import math

    r = max(2, size // 2 + 1)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    if size < 6:
        return
    inner = r + 1
    outer = size + 1
    for i in range(8):
        angle = i * math.pi / 4
        x1 = cx + inner * math.cos(angle)
        y1 = cy + inner * math.sin(angle)
        x2 = cx + outer * math.cos(angle)
        y2 = cy + outer * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=0, width=1)


def _draw_flower(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 7) -> None:
    if size < 6:
        # Petals can't resolve below ~6px; degrade to a chunky dot like heart.
        r = max(1, size // 2)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
        return
    pr = max(2, size // 3)
    offset = size - pr + 1
    for dx, dy in ((0, -offset), (offset, 0), (0, offset), (-offset, 0)):
        draw.ellipse(
            (cx + dx - pr, cy + dy - pr, cx + dx + pr, cy + dy + pr),
            fill=0,
        )
    cr = max(1, size // 4)
    draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=1)


_ACCENTS: dict[str, AccentFn] = {
    "heart": _draw_heart,
    "star": _draw_star,
    "balloon": _draw_balloon,
    "moon": _draw_moon,
    "sun": _draw_sun,
    "flower": _draw_flower,
}


# Frame geometry. The outer black line sits at the panel edge; the red beads
# trim the inside of that line. The text region must clear FRAME_PAD on every
# side so it doesn't collide with the trim.
FRAME_OUTER = 1            # 1px inset for the rounded black line
FRAME_BEAD_INSET = 5       # bead centers sit FRAME_BEAD_INSET px from the edge
FRAME_BEAD_SPACING = 10
FRAME_PAD = 9              # min y-distance from text to the panel edge

# Hero baseline. Two-line mode (extended) sits the hero high to leave room for
# the sub line; one-line mode (days/hours) centers it vertically: the hero is
# 28pt, so (HEIGHT - 28) // 2 == 47.
HERO_Y_TWO_LINE = 33
HERO_Y_ONE_LINE = 47


def _draw_bead(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    draw.ellipse((cx - 1, cy - 1, cx + 1, cy + 1), fill=0)


def _draw_corner_dot(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=0)


def _draw_frame(
    bd: ImageDraw.ImageDraw,
    rd: ImageDraw.ImageDraw,
    accent: str,
    accent_fn: AccentFn,
) -> None:
    # Outer rounded black hairline.
    bd.rounded_rectangle(
        (FRAME_OUTER, FRAME_OUTER, WIDTH - 1 - FRAME_OUTER, HEIGHT - 1 - FRAME_OUTER),
        radius=8,
        outline=0,
        width=1,
    )

    # Red beads, evenly spaced along each inside edge, skipping the corners
    # so they don't clash with the rounded outer line or the corner accents.
    inset = FRAME_BEAD_INSET
    left, right = inset, WIDTH - 1 - inset
    top, bottom = inset, HEIGHT - 1 - inset
    corner_skip = 14

    for x in range(left + corner_skip, right - corner_skip + 1, FRAME_BEAD_SPACING):
        _draw_bead(rd, x, top)
        _draw_bead(rd, x, bottom)
    for y in range(top + corner_skip, bottom - corner_skip + 1, FRAME_BEAD_SPACING):
        _draw_bead(rd, left, y)
        _draw_bead(rd, right, y)

    corners = ((9, 9), (WIDTH - 10, 9), (9, HEIGHT - 10), (WIDTH - 10, HEIGHT - 10))
    for cx, cy in corners:
        if accent == "heart":
            _draw_corner_dot(rd, cx, cy)
        else:
            accent_fn(rd, cx, cy, size=4)


def _format_birthday(born_at: datetime) -> str:
    return born_at.strftime("%b ") + str(born_at.day) + born_at.strftime(", %Y")


def render(
    name: str,
    age: AgeBreakdown,
    born_at: datetime,
    accent: str = "heart",
    flip: bool = False,
    age_format: str = "extended",
    special: str | None = None,
    after_hours: bool = False,
    quiet: bool = False,
) -> tuple[Image.Image, Image.Image]:
    black = Image.new("1", (WIDTH, HEIGHT), 1)
    red = Image.new("1", (WIDTH, HEIGHT), 1)
    bd = ImageDraw.Draw(black)
    rd = ImageDraw.Draw(red)

    accent_fn = _ACCENTS.get(accent, _draw_heart)

    _draw_frame(bd, rd, accent, accent_fn)

    header_font = _font(20, "Medium")
    header = f"{name} is"
    hw = _text_width(rd, header, header_font)
    hx = (WIDTH - hw) // 2
    hy = FRAME_PAD
    rd.text((hx, hy), header, font=header_font, fill=0)

    accent_y = hy + 10
    accent_fn(rd, hx - 14, accent_y)
    accent_fn(rd, hx + hw + 14, accent_y)

    if quiet:
        # Last refresh before sleep_hour: the panel will freeze on this image
        # overnight, so hide every volatile metric (days/hours sub, full-mode
        # totals) and keep only the slow-moving years/months hero. Wins over
        # both `special` and `age_format`.
        hero = _hero_line(age)
        hero_y = HERO_Y_TWO_LINE
        sub = None
    elif special is not None:
        # Special-day mode (birthday, milestone, ...) hijacks the hero row and
        # demotes the standard "Y years M months" phrasing to the sub line,
        # regardless of age_format. The two-line baseline is reused so the sub
        # line lands at its usual y=68.
        hero = special
        hero_y = HERO_Y_TWO_LINE
        sub = _hero_line(age)
    elif age_format == "days":
        hero = pluralize(age.total_days, "day") if age.total_days else "newborn"
        hero_y = HERO_Y_ONE_LINE
        sub = None
    elif age_format == "hours":
        hero = pluralize(age.total_hours, "hour") if age.total_hours else "newborn"
        hero_y = HERO_Y_ONE_LINE
        sub = None
    else:
        hero = _hero_line(age)
        hero_y = HERO_Y_TWO_LINE
        sub = _sub_line(age)

    hero_size = 28
    hero_font = _font(hero_size, "Bold")
    while _text_width(bd, hero, hero_font) > WIDTH - 28 and hero_size > 16:
        hero_size -= 2
        hero_font = _font(hero_size, "Bold")
    _draw_centered(bd, hero_y, hero, hero_font)

    if sub is not None:
        sub_font = _font(17, "Medium")
        _draw_centered(bd, 68, sub, sub_font)

    footer_font = _font(13, "Regular")
    footer = f"since {_format_birthday(born_at)}"
    fw = _text_width(rd, footer, footer_font)
    fx = (WIDTH - fw) // 2
    fy = HEIGHT - FRAME_PAD - 13
    rd.text((fx, fy), footer, font=footer_font, fill=0)
    if accent != "heart":
        accent_fn(rd, fx - 12, fy + 8, size=7)

    # `full` augments the extended layout with compact total_days /
    # total_hours readouts in the bottom corners, on the black plane so they
    # contrast with the red footer between them. Skipped in quiet mode since
    # those totals would freeze on the panel overnight.
    if age_format == "full" and not quiet:
        totals_size = 15
        totals_font = _font(totals_size, "Regular")
        left_total = f"{age.total_days}d"
        right_total = f"{age.total_hours}h"
        rt_w = _text_width(bd, right_total, totals_font)
        # Top-align so the totals' bottom matches the 13pt footer's bottom,
        # keeping a single visual baseline in the row.
        totals_y = HEIGHT - FRAME_PAD - totals_size
        bd.text((14, totals_y), left_total, font=totals_font, fill=0)
        bd.text((WIDTH - 14 - rt_w, totals_y), right_total, font=totals_font, fill=0)

    if after_hours:
        # Swap 0↔1 on the black plane: white panel background becomes black
        # ink, drawn text becomes "no ink" (bare panel = white).
        inverted = black.point(lambda px: 0 if px else 1)
        # The Waveshare driver ORs the two planes onto the panel, so a
        # uniformly-black plane would mask out every red bead/accent. Punch
        # black back out wherever red has ink so red stays visible against
        # the new black background — the user wants black/white inverted
        # but red preserved.
        rp = red.load()
        bp = inverted.load()
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if rp[x, y] == 0:
                    bp[x, y] = 1
        black = inverted

    if flip:
        black = black.rotate(180)
        red = red.rotate(180)

    return black, red


def compose_preview(black: Image.Image, red: Image.Image) -> Image.Image:
    out = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    px = out.load()
    bp = black.load()
    rp = red.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if bp[x, y] == 0:
                px[x, y] = (0, 0, 0)
            elif rp[x, y] == 0:
                px[x, y] = (220, 30, 30)
    return out
