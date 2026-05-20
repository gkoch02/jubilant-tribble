from datetime import UTC, datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

from kidage.age import AgeBreakdown
from kidage.render import (
    FRAME_BEAD_INSET,
    FRAME_OUTER,
    FRAME_PAD,
    HEIGHT,
    WIDTH,
    _draw_balloon,
    _draw_bead,
    _draw_centered,
    _draw_corner_dot,
    _draw_flower,
    _draw_frame,
    _draw_heart,
    _draw_moon,
    _draw_star,
    _draw_sun,
    _font,
    _format_birthday,
    _hero_line,
    _sub_line,
    compose_preview,
    render,
)

PT = timezone(timedelta(hours=-7))
BORN = datetime(2022, 9, 12, 3, 47, tzinfo=PT)

# Canonical age fixtures. Totals are realistic for the calendar values so that
# format="days"/"hours" rendering is exercised with plausible inputs.
AGE = AgeBreakdown(3, 7, 15, 4, total_days=1324, total_hours=31780)
NEWBORN = AgeBreakdown(0, 0, 0, 1, total_days=0, total_hours=1)
TWO_YEARS = AgeBreakdown(2, 0, 0, 0, total_days=730, total_hours=17520)
LONG_AGE = AgeBreakdown(99, 11, 30, 23, total_days=36524, total_hours=876575)


def _has_ink(img):
    # Any byte < 0xff means at least one of its 8 packed pixels is black.
    # Checking for b"\x00" directly would miss thin or cutout glyphs that
    # never leave 8 byte-aligned contiguous black pixels (e.g. moon, flower).
    return any(byte != 0xFF for byte in img.tobytes())


def _ink_x_extent(img, y_range, x_range=None):
    """Return (min_x, max_x) of inked pixels in the given y/x range, or None."""
    px = img.load()
    x_range = x_range or range(WIDTH)
    xs = [x for y in y_range for x in x_range if px[x, y] == 0]
    return (min(xs), max(xs)) if xs else None


def test_render_returns_two_planes_at_panel_size():
    black, red = render("Lilah", AGE, BORN)
    assert black.size == (WIDTH, HEIGHT)
    assert red.size == (WIDTH, HEIGHT)
    assert black.mode == "1"
    assert red.mode == "1"
    assert _has_ink(black)
    assert _has_ink(red)


def test_render_handles_newborn():
    black, red = render("Lilah", NEWBORN, BORN)
    assert _has_ink(black)


def test_render_flip_rotates_both_planes():
    upright = render("Lilah", AGE, BORN, flip=False)
    flipped = render("Lilah", AGE, BORN, flip=True)
    assert upright[0].tobytes() != flipped[0].tobytes()
    assert upright[1].tobytes() != flipped[1].tobytes()


def test_render_after_hours_inverts_black_only():
    """after_hours flips black/white but leaves red untouched, so the
    panel reads white-on-black with red beads still in place."""
    normal = render("Lilah", AGE, BORN)
    inverted = render("Lilah", AGE, BORN, after_hours=True)
    assert normal[0].tobytes() != inverted[0].tobytes()
    assert normal[1].tobytes() == inverted[1].tobytes()


def test_render_after_hours_makes_background_inked():
    """After inversion, what used to be the white panel background should
    now be inked on the black plane. Sample a margin pixel that's outside
    the frame and well clear of any glyphs."""
    normal_black, _ = render("Lilah", AGE, BORN)
    inv_black, _ = render("Lilah", AGE, BORN, after_hours=True)
    np = normal_black.load()
    ip = inv_black.load()
    # (0, 0) is the very top-left corner — outside the rounded frame, so
    # it's blank white in the normal render and should be ink after
    # inversion.
    assert np[0, 0] == 1
    assert ip[0, 0] == 0


def test_render_after_hours_punches_black_out_under_red_ink():
    """The Waveshare driver ORs the two planes onto the panel, so a
    naive 'invert all of black' would mask out red. Verify that wherever
    the red plane has ink, the inverted black plane is *not* inked, so
    red still shows through against the new black background."""
    _, red = render("Lilah", AGE, BORN)
    inv_black, _ = render("Lilah", AGE, BORN, after_hours=True)
    rp = red.load()
    bp = inv_black.load()
    red_pixels = [
        (x, y) for y in range(HEIGHT) for x in range(WIDTH) if rp[x, y] == 0
    ]
    assert red_pixels, "expected the normal render to produce some red ink"
    for x, y in red_pixels:
        assert bp[x, y] == 1, (
            f"black plane is inked at red pixel ({x}, {y}) — "
            "would mask red on the panel"
        )


def test_render_after_hours_combines_with_flip():
    """flip and after_hours are independent and must compose. Inverted-
    then-flipped should differ from just-inverted, just-flipped, and
    plain renders."""
    plain = render("Lilah", AGE, BORN)[0].tobytes()
    flipped = render("Lilah", AGE, BORN, flip=True)[0].tobytes()
    inverted = render("Lilah", AGE, BORN, after_hours=True)[0].tobytes()
    both = render("Lilah", AGE, BORN, flip=True, after_hours=True)[0].tobytes()
    assert len({plain, flipped, inverted, both}) == 4


def test_compose_preview_is_rgb_panel_size():
    black, red = render("Lilah", AGE, BORN)
    p = compose_preview(black, red)
    assert p.size == (WIDTH, HEIGHT)
    assert p.mode == "RGB"


ACCENTS = ("heart", "star", "balloon", "moon", "sun", "flower")


def test_render_accepts_known_accents():
    for accent in ACCENTS:
        b, r = render("Lilah", TWO_YEARS, BORN, accent=accent)
        assert _has_ink(r)


def test_accents_produce_distinct_red_planes():
    """Each accent must actually paint differently; otherwise an accent-fn
    regression (e.g. _ACCENTS.get always returning the default) would slip
    past the existing "ink exists" check."""
    planes = [
        render("Lilah", TWO_YEARS, BORN, accent=a)[1].tobytes() for a in ACCENTS
    ]
    for i, a in enumerate(planes):
        for b in planes[i + 1 :]:
            assert a != b


def test_text_clears_frame_pad_margin():
    """Text must not bleed into the FRAME_PAD margin rows.

    CLAUDE.md: 'Resizing text or moving the frame in isolation will produce
    clipping; adjust both.' We sample the central x-band (skipping the
    rounded-corner arcs of the outer black hairline) and assert no black
    text ink in the top and bottom keep-out strips.
    """
    black, _ = render("Lilah", AGE, BORN)
    bp = black.load()

    for y in range(2, FRAME_PAD):
        for x in range(20, WIDTH - 20):
            assert bp[x, y] == 1, f"black ink in top margin at ({x}, {y})"
    for y in range(HEIGHT - FRAME_PAD, HEIGHT - 2):
        for x in range(20, WIDTH - 20):
            assert bp[x, y] == 1, f"black ink in bottom margin at ({x}, {y})"


def test_hero_auto_shrinks_to_stay_within_width_budget():
    """The hero shrink loop (render.py:168) caps text width at WIDTH-28.
    A long hero like '99 years  11 months' should still center within the
    budgeted band (left edge >= 14, right edge <= WIDTH-14). We restrict
    the x search to skip the frame outline at x=1 and x=WIDTH-2."""
    black, _ = render("Lilah", LONG_AGE, BORN)
    inner = range(10, WIDTH - 10)
    extent = _ink_x_extent(black, range(33, 62), inner)
    assert extent is not None, "expected hero ink"
    left, right = extent
    assert left >= 14, f"hero overflows left budget: {left}"
    assert right <= WIDTH - 14, f"hero overflows right budget: {right}"


def test_format_modes_produce_distinct_planes():
    """Each age_format must visibly change the black plane; otherwise a
    regression that ignored the new field would slip past the per-format
    smoke checks below."""
    planes = {
        fmt: render("Lilah", AGE, BORN, age_format=fmt)[0].tobytes()
        for fmt in ("extended", "days", "hours", "full")
    }
    assert planes["extended"] != planes["days"]
    assert planes["days"] != planes["hours"]
    assert planes["extended"] != planes["hours"]
    assert planes["extended"] != planes["full"]
    assert planes["days"] != planes["full"]


def test_format_full_adds_ink_in_bottom_corners():
    """`full` augments the extended layout with compact total readouts in
    the bottom-left and bottom-right of the black plane. The two corners
    must gain ink relative to plain extended; otherwise the totals aren't
    actually being painted."""
    extended_black, _ = render("Lilah", AGE, BORN, age_format="extended")
    full_black, _ = render("Lilah", AGE, BORN, age_format="full")
    footer_band = range(HEIGHT - FRAME_PAD - 13, HEIGHT - FRAME_PAD)
    left = range(10, 60)
    right = range(WIDTH - 60, WIDTH - 10)
    ext_left = _ink_x_extent(extended_black, footer_band, left)
    full_left = _ink_x_extent(full_black, footer_band, left)
    ext_right = _ink_x_extent(extended_black, footer_band, right)
    full_right = _ink_x_extent(full_black, footer_band, right)
    assert ext_left is None and full_left is not None, (
        "full mode should add black ink in the bottom-left corner"
    )
    assert ext_right is None and full_right is not None, (
        "full mode should add black ink in the bottom-right corner"
    )


def test_format_full_uses_total_fields_not_calendar():
    """The corner totals must reflect age.total_days / age.total_hours.
    Two ages with identical calendar (years/months/days/hours) but
    different totals should diverge in the bottom band of the black
    plane (where the hero/sub above is identical)."""
    big = AgeBreakdown(3, 7, 15, 4, total_days=1324, total_hours=31780)
    small = AgeBreakdown(3, 7, 15, 4, total_days=42, total_hours=999)
    big_black, _ = render("Lilah", big, BORN, age_format="full")
    small_black, _ = render("Lilah", small, BORN, age_format="full")
    assert big_black.tobytes() != small_black.tobytes()


def test_format_full_preserves_extended_hero_and_sub():
    """`full` differs from `extended` only in the footer row. The hero
    band (y=33..62) and sub band (y=68..86) must be byte-identical so
    layout regressions in the upper region get caught here rather than
    drowning in the bottom-corner diff."""
    extended_black, _ = render("Lilah", AGE, BORN, age_format="extended")
    full_black, _ = render("Lilah", AGE, BORN, age_format="full")
    ep = extended_black.load()
    fp = full_black.load()
    for y in list(range(33, 62)) + list(range(68, 86)):
        for x in range(WIDTH):
            assert ep[x, y] == fp[x, y], (
                f"upper layout diverges at ({x}, {y})"
            )


def test_format_days_short_circuits_zero_to_newborn():
    """In days mode, total_days=0 must render "newborn" rather than
    "0 days". We pin this by rendering the same AgeBreakdown in days
    mode and in hours mode (with the total_hours also 0): both fall
    into the newborn branch, so their hero text — and thus the black
    plane below the header — should be identical."""
    fresh = AgeBreakdown(0, 0, 0, 0, total_days=0, total_hours=0)
    days_black, _ = render("Lilah", fresh, BORN, age_format="days")
    hours_black, _ = render("Lilah", fresh, BORN, age_format="hours")
    assert days_black.tobytes() == hours_black.tobytes()


def test_format_days_uses_total_days_not_calendar_days():
    """Hero text in days mode must reflect total_days (e.g. 1324) rather
    than the calendar `days` field (15). If render() reads age.days by
    mistake, a small total_days input renders the same as a small
    calendar-days input — pin the distinction."""
    big = AgeBreakdown(0, 0, 15, 0, total_days=1324, total_hours=31780)
    small = AgeBreakdown(0, 0, 15, 0, total_days=15, total_hours=360)
    big_black, _ = render("Lilah", big, BORN, age_format="days")
    small_black, _ = render("Lilah", small, BORN, age_format="days")
    assert big_black.tobytes() != small_black.tobytes()


def test_special_hero_replaces_normal_hero():
    """In special-day mode the hero text is the override string, and the
    standard "Y years M months" phrasing is demoted to the sub line — so
    the black plane must differ from the non-special render."""
    plain = render("Lilah", AGE, BORN)[0].tobytes()
    special = render("Lilah", AGE, BORN, special="Happy 4th Birthday!")[0].tobytes()
    assert plain != special


def test_special_overrides_days_format():
    """Special days take over regardless of age_format. Pin this so a future
    refactor doesn't accidentally restore the days/hours hero on a milestone."""
    days = render("Lilah", AGE, BORN, age_format="days")[0].tobytes()
    special = render(
        "Lilah", AGE, BORN, age_format="days", special="1000 days!"
    )[0].tobytes()
    assert days != special


def test_special_long_label_respects_width_budget():
    """'Happy 99th Birthday!' must shrink rather than overflow the frame —
    the same shrink loop the standard hero relies on."""
    black, _ = render("Lilah", LONG_AGE, BORN, special="Happy 99th Birthday!")
    inner = range(10, WIDTH - 10)
    extent = _ink_x_extent(black, range(33, 62), inner)
    assert extent is not None
    left, right = extent
    assert left >= 14
    assert right <= WIDTH - 14


def test_long_hero_would_overflow_at_default_size():
    """Sanity check that the budget test above actually exercises the shrink
    path: '99 years  11 months' at 28pt Bold must exceed WIDTH-28. If the
    font ever changes to narrower glyphs and this stops being true, the
    budget test no longer proves shrink works — pick a longer input."""
    from kidage.render import _text_width

    bd = ImageDraw.Draw(Image.new("1", (WIDTH, HEIGHT), 1))
    f28 = _font(28, "Bold")
    assert _text_width(bd, "99 years  11 months", f28) > WIDTH - 28


# ---------------------------------------------------------------------------
# _format_birthday
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("born_at,expected", [
    (datetime(2022, 9, 1, tzinfo=UTC), "Sep 1, 2022"),
    (datetime(2022, 9, 12, tzinfo=UTC), "Sep 12, 2022"),
    (datetime(2020, 12, 25, tzinfo=UTC), "Dec 25, 2020"),
    (datetime(2020, 2, 29, tzinfo=UTC), "Feb 29, 2020"),
])
def test_format_birthday(born_at, expected):
    assert _format_birthday(born_at) == expected


# ---------------------------------------------------------------------------
# _hero_line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("age,expected", [
    (AgeBreakdown(0, 0, 0, 0, 0, 0), "newborn"),
    (AgeBreakdown(0, 1, 0, 0, 0, 0), "1 month"),
    (AgeBreakdown(0, 5, 0, 0, 0, 0), "5 months"),
    (AgeBreakdown(1, 0, 0, 0, 365, 8760), "1 year  0 months"),
    (AgeBreakdown(3, 7, 15, 4, 1324, 31780), "3 years  7 months"),
])
def test_hero_line(age, expected):
    assert _hero_line(age) == expected


# ---------------------------------------------------------------------------
# _sub_line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("age,expected", [
    (AgeBreakdown(0, 0, 0, 0, 0, 0), "0 days  ·  0 hours"),
    (AgeBreakdown(0, 0, 1, 1, 0, 0), "1 day  ·  1 hour"),
    (AgeBreakdown(3, 7, 15, 4, 0, 0), "15 days  ·  4 hours"),
])
def test_sub_line(age, expected):
    assert _sub_line(age) == expected


# ---------------------------------------------------------------------------
# _draw_centered
# ---------------------------------------------------------------------------


def test_draw_centered_horizontally_centers_text():
    img = Image.new("1", (WIDTH, HEIGHT), 1)
    draw = ImageDraw.Draw(img)
    font = _font(20, "Regular")
    _draw_centered(draw, 40, "hello world", font)
    px = img.load()
    inked_xs = [x for x in range(WIDTH) for y in range(35, 75) if px[x, y] == 0]
    assert inked_xs, "expected text ink after _draw_centered"
    visual_center = (min(inked_xs) + max(inked_xs)) / 2
    assert abs(visual_center - WIDTH / 2) < 5, (
        f"text center {visual_center:.1f} is not near panel center {WIDTH / 2}"
    )


# ---------------------------------------------------------------------------
# Accent drawing primitives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fn,size", [
    (_draw_heart, 9),
    (_draw_star, 8),
    (_draw_balloon, 10),
    (_draw_moon, 8),
    (_draw_sun, 8),
    (_draw_flower, 7),
])
def test_accent_fn_paints_ink_near_center(fn, size):
    cx, cy = 50, 50
    img = Image.new("1", (120, 120), 1)
    draw = ImageDraw.Draw(img)
    fn(draw, cx, cy, size=size)
    px = img.load()
    # Generous bounding box: 2× size + tail room for balloon string
    margin = size * 2 + 6
    inked = [
        (x, y)
        for x in range(max(0, cx - margin), min(120, cx + margin + 1))
        for y in range(max(0, cy - margin), min(120, cy + margin + 1))
        if px[x, y] == 0
    ]
    assert inked, f"{fn.__name__} painted no ink in the expected region"


def test_draw_bead_paints_small_dot():
    cx, cy = 20, 20
    img = Image.new("1", (50, 50), 1)
    draw = ImageDraw.Draw(img)
    _draw_bead(draw, cx, cy)
    px = img.load()
    inked = [(x, y) for x in range(50) for y in range(50) if px[x, y] == 0]
    assert inked, "bead painted no ink"
    for x, y in inked:
        assert abs(x - cx) <= 2 and abs(y - cy) <= 2, (
            f"bead ink at ({x},{y}) is outside radius-1 ellipse from ({cx},{cy})"
        )


def test_draw_corner_dot_paints_small_dot():
    cx, cy = 20, 20
    img = Image.new("1", (50, 50), 1)
    draw = ImageDraw.Draw(img)
    _draw_corner_dot(draw, cx, cy)
    px = img.load()
    inked = [(x, y) for x in range(50) for y in range(50) if px[x, y] == 0]
    assert inked, "corner dot painted no ink"
    for x, y in inked:
        assert abs(x - cx) <= 3 and abs(y - cy) <= 3, (
            f"corner dot ink at ({x},{y}) is outside radius-2 ellipse from ({cx},{cy})"
        )


def test_draw_corner_dot_is_larger_than_bead():
    """corner_dot (radius 2) must cover more pixels than bead (radius 1)."""
    img_bead = Image.new("1", (50, 50), 1)
    img_dot = Image.new("1", (50, 50), 1)
    cx, cy = 20, 20
    _draw_bead(ImageDraw.Draw(img_bead), cx, cy)
    _draw_corner_dot(ImageDraw.Draw(img_dot), cx, cy)
    bp = img_bead.load()
    dp = img_dot.load()
    bead_count = sum(1 for x in range(50) for y in range(50) if bp[x, y] == 0)
    dot_count = sum(1 for x in range(50) for y in range(50) if dp[x, y] == 0)
    assert dot_count > bead_count


# ---------------------------------------------------------------------------
# _draw_frame
# ---------------------------------------------------------------------------


def _make_frame_pair(accent, accent_fn):
    black = Image.new("1", (WIDTH, HEIGHT), 1)
    red = Image.new("1", (WIDTH, HEIGHT), 1)
    _draw_frame(ImageDraw.Draw(black), ImageDraw.Draw(red), accent, accent_fn)
    return black, red


def test_draw_frame_outer_black_border_on_all_four_sides():
    black, _ = _make_frame_pair("star", _draw_star)
    bp = black.load()
    mid_x, mid_y = WIDTH // 2, HEIGHT // 2
    assert bp[mid_x, FRAME_OUTER] == 0, "top border missing"
    assert bp[mid_x, HEIGHT - 1 - FRAME_OUTER] == 0, "bottom border missing"
    assert bp[FRAME_OUTER, mid_y] == 0, "left border missing"
    assert bp[WIDTH - 1 - FRAME_OUTER, mid_y] == 0, "right border missing"


def test_draw_frame_red_beads_on_all_four_rails():
    _, red = _make_frame_pair("star", _draw_star)
    rp = red.load()
    inset = FRAME_BEAD_INSET
    assert any(rp[x, inset] == 0 for x in range(WIDTH)), "no red beads on top rail"
    assert any(rp[x, HEIGHT - 1 - inset] == 0 for x in range(WIDTH)), "no red beads on bottom rail"
    assert any(rp[inset, y] == 0 for y in range(HEIGHT)), "no red beads on left rail"
    assert any(rp[WIDTH - 1 - inset, y] == 0 for y in range(HEIGHT)), "no red beads on right rail"


def test_draw_frame_heart_uses_corner_dots_not_small_hearts():
    """Heart accent must use corner dots (not small hearts) in frame corners.

    _draw_heart(size=4) places a polygon tip at cy+4 along the center column.
    _draw_corner_dot(radius=2) only reaches cy+2. Pixels at cy+3 and cy+4
    distinguish the two: a regression that switches back to small hearts inks
    those pixels; corner dots leave them blank.

    Bead rails and the outer border don't touch these positions: beads are
    clamped to x in [19, 230] while the corner x values are 9 and 240.
    """
    corners = ((9, 9), (WIDTH - 10, 9), (9, HEIGHT - 10), (WIDTH - 10, HEIGHT - 10))
    _, red = _make_frame_pair("heart", _draw_heart)
    rp = red.load()
    for cx, cy in corners:
        for dy in (3, 4):
            y = cy + dy
            if 0 <= y < HEIGHT:
                assert rp[cx, y] == 1, (
                    f"corner ({cx},{cy}): pixel ({cx},{y}) is inked — "
                    "looks like a small heart, not a corner dot"
                )


# ---------------------------------------------------------------------------
# after_hours × all accents
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# quiet (last-refresh-before-sleep) mode
# ---------------------------------------------------------------------------


def test_quiet_drops_sub_line():
    """Quiet mode hides the days/hours sub line, so the band where the sub
    normally sits (y=68..86) loses its text ink. Constrain x to skip the
    frame's outer hairline at x=1 and x=WIDTH-2."""
    normal_black, _ = render("Lilah", AGE, BORN, age_format="extended")
    quiet_black, _ = render("Lilah", AGE, BORN, age_format="extended", quiet=True)
    sub_band = range(68, 86)
    inner = range(20, WIDTH - 20)
    assert _ink_x_extent(normal_black, sub_band, inner) is not None
    assert _ink_x_extent(quiet_black, sub_band, inner) is None


def test_quiet_keeps_hero_at_two_line_baseline():
    """Quiet mode must keep the years/months hero at HERO_Y_TWO_LINE (y=33),
    not recenter to HERO_Y_ONE_LINE — the user wants the hero in the same
    spot as the daytime extended layout so the panel doesn't visually
    shift at the daily flip into quiet hours."""
    extended_black, _ = render("Lilah", AGE, BORN, age_format="extended")
    quiet_black, _ = render("Lilah", AGE, BORN, age_format="extended", quiet=True)
    ep = extended_black.load()
    qp = quiet_black.load()
    # Hero band is byte-identical when only the sub differs.
    for y in range(33, 62):
        for x in range(WIDTH):
            assert ep[x, y] == qp[x, y], f"hero diverges at ({x}, {y})"


def test_quiet_keeps_footer_since_date():
    """The "since <date>" footer is static, not a stale metric — it stays."""
    quiet_black, quiet_red = render("Lilah", AGE, BORN, quiet=True)
    footer_band = range(HEIGHT - FRAME_PAD - 13, HEIGHT - FRAME_PAD)
    assert _ink_x_extent(quiet_red, footer_band) is not None


def test_quiet_drops_full_mode_corner_totals():
    """`full` augments extended with bottom-corner total_days/total_hours
    readouts, but those would go stale overnight — quiet must suppress them."""
    full_black, _ = render("Lilah", AGE, BORN, age_format="full")
    quiet_black, _ = render("Lilah", AGE, BORN, age_format="full", quiet=True)
    footer_band = range(HEIGHT - FRAME_PAD - 13, HEIGHT - FRAME_PAD)
    left = range(10, 60)
    right = range(WIDTH - 60, WIDTH - 10)
    assert _ink_x_extent(full_black, footer_band, left) is not None
    assert _ink_x_extent(full_black, footer_band, right) is not None
    assert _ink_x_extent(quiet_black, footer_band, left) is None
    assert _ink_x_extent(quiet_black, footer_band, right) is None


def test_quiet_overrides_special_day():
    """The user picked: at sleep_hour, quiet wins over a birthday/milestone
    hero. A birthday render in quiet mode must match a non-special quiet
    render — the birthday string never appears."""
    bday_quiet = render(
        "Lilah", AGE, BORN, special="Happy 4th Birthday!", quiet=True
    )[0].tobytes()
    plain_quiet = render("Lilah", AGE, BORN, quiet=True)[0].tobytes()
    assert bday_quiet == plain_quiet


def test_quiet_overrides_age_format_days():
    """Quiet wins over age_format too — a "days" config at sleep_hour must
    not show the days hero (would freeze a stale "1324 days" overnight)."""
    days_quiet = render("Lilah", AGE, BORN, age_format="days", quiet=True)[0].tobytes()
    plain_quiet = render("Lilah", AGE, BORN, quiet=True)[0].tobytes()
    assert days_quiet == plain_quiet


def test_quiet_combines_with_after_hours():
    """Quiet and after_hours are independent and must compose. At ~sunset on
    sleep_hour, both are on; both passes should still produce a usable image
    (red ink not masked by the inverted black plane)."""
    inv_black, red = render("Lilah", AGE, BORN, after_hours=True, quiet=True)
    rp = red.load()
    bp = inv_black.load()
    red_pixels = [(x, y) for y in range(HEIGHT) for x in range(WIDTH) if rp[x, y] == 0]
    assert red_pixels
    for x, y in red_pixels:
        assert bp[x, y] == 1, f"quiet+after_hours masks red at ({x},{y})"


def test_hero_shrink_loop_stops_at_16pt_floor():
    """The hero shrink loop bottoms out at 16pt (`hero_size > 16`). For text
    that even 16pt can't fit, the loop should stop — not crash, not loop
    forever. Pin the floor by rendering an overlong special and checking
    that ink lands in the hero band (i.e. the loop exited cleanly)."""
    overlong = "Happy 100th Birthday from Grandma and Grandpa!"
    black, _ = render("Lilah", AGE, BORN, special=overlong)
    # Ink in the hero band confirms we exited the shrink loop and painted
    # something — even if the something clips the budget.
    extent = _ink_x_extent(black, range(33, 62))
    assert extent is not None


def test_long_name_in_header_is_pinned_behavior():
    """The header `{name} is` has no shrink loop — a long name will paint
    wherever the centered string lands. Pin current behavior: a 20-char
    name still renders ink in the header band without crashing. If a
    future change adds shrink/clip logic, this test should be updated
    intentionally rather than silently breaking."""
    long_name = "Maximilian Aurelius"
    black, red = render(long_name, AGE, BORN)
    # Header sits at y=FRAME_PAD, ~20pt tall.
    header_band = range(FRAME_PAD, FRAME_PAD + 20)
    assert _ink_x_extent(red, header_band) is not None


def test_flip_after_hours_red_plane_matches_flipped_normal():
    """Order of operations: render() inverts the black plane first, then
    rotates both planes together. So the red plane in (flip + after_hours)
    must equal the red plane in plain flip — inversion only touches black."""
    flip_only = render("Lilah", AGE, BORN, flip=True)
    both = render("Lilah", AGE, BORN, flip=True, after_hours=True)
    assert flip_only[1].tobytes() == both[1].tobytes()


def test_heart_accent_omits_footer_accent_glyph():
    """The heart theme intentionally omits the footer accent (the small
    heart at 4px lost its shape — CLAUDE.md says so). Every other accent
    paints a small glyph just left of the centered "since …" footer.
    This test pins that contract by comparing the column to the left of
    the footer text on heart vs. star: star inks it, heart doesn't.
    """
    _, heart_red = render("Lilah", AGE, BORN, accent="heart")
    _, star_red = render("Lilah", AGE, BORN, accent="star")
    # The footer accent sits at fx - 12 on the red plane, y = fy + 8.
    # We don't know the exact fx without recomputing, but we know it lands
    # in the bottom band's left third. Look for ink in a tight column band
    # in the bottom strip that heart should leave blank.
    footer_band = range(HEIGHT - FRAME_PAD - 13, HEIGHT - FRAME_PAD)
    # Sample columns to the left of where the footer text starts — well
    # inside the panel but outside the frame's bead rail.
    left_of_footer = range(30, 60)
    heart_extent = _ink_x_extent(heart_red, footer_band, left_of_footer)
    star_extent = _ink_x_extent(star_red, footer_band, left_of_footer)
    # Star paints a glyph in that band; heart should not.
    assert star_extent is not None, "star should paint a footer accent glyph"
    assert heart_extent is None, (
        "heart should omit the footer accent glyph — small hearts lose shape "
        "at 4px and CLAUDE.md pins this carve-out"
    )


def test_compose_preview_color_mapping():
    """compose_preview maps black-plane ink to (0,0,0), red-plane ink (where
    black is blank) to (220,30,30), and otherwise white. Verify each pixel
    class lands on the right RGB triple."""
    black = Image.new("1", (WIDTH, HEIGHT), 1)
    red = Image.new("1", (WIDTH, HEIGHT), 1)
    # Black ink at (10, 10), red ink at (20, 20), nothing at (30, 30).
    black.putpixel((10, 10), 0)
    red.putpixel((20, 20), 0)
    # Overlap pixel: both planes inked — black plane wins in compose_preview.
    black.putpixel((40, 40), 0)
    red.putpixel((40, 40), 0)
    out = compose_preview(black, red)
    assert out.getpixel((10, 10)) == (0, 0, 0)
    assert out.getpixel((20, 20)) == (220, 30, 30)
    assert out.getpixel((30, 30)) == (255, 255, 255)
    assert out.getpixel((40, 40)) == (0, 0, 0)


@pytest.mark.parametrize("accent", ACCENTS)
def test_after_hours_punches_black_under_red_all_accents(accent):
    """For every accent, red ink must not be masked by the inverted black plane.
    Accent-specific branches in _draw_frame mean regressions can be accent-local."""
    _, red = render("Lilah", AGE, BORN, accent=accent)
    inv_black, _ = render("Lilah", AGE, BORN, accent=accent, after_hours=True)
    rp = red.load()
    bp = inv_black.load()
    red_pixels = [(x, y) for y in range(HEIGHT) for x in range(WIDTH) if rp[x, y] == 0]
    assert red_pixels, f"accent={accent!r}: expected red ink"
    for x, y in red_pixels:
        assert bp[x, y] == 1, (
            f"accent={accent!r}: black plane masks red pixel ({x},{y})"
        )
