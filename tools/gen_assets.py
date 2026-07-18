"""Regenerates Orrery's programmatic drawables and the embedded font subset.

Run from anywhere:  py tools/gen_assets.py [--check]

  (default)  writes assets into watchface/src/main/res/drawable/ and res/font/
  --check    regenerates in memory and reports any pixel/byte drift vs the repo

Fully generated here (byte-reproducible; --check verifies exact bytes):
hour_dial (disc + numerals + burgee), date_ring, day_dial, batt_dial,
day_hand, date_oval, res/font/shantell.ttf. Everything else in drawable/
(tick_ring, hands, preview) is committed baked art from prototyping; its
history lives in git.

Typography note: all text renders from tools/fonts/ShantellSans.ttf at the
font's default variable instance. That default rendering is the approved look;
do not "fix" it to a heavier named weight without re-approving on-watch.
"""
import argparse
import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DRAW = ROOT / "watchface" / "src" / "main" / "res" / "drawable"
RES_FONT = ROOT / "watchface" / "src" / "main" / "res" / "font" / "shantell.ttf"
SHANTELL = ROOT / "tools" / "fonts" / "ShantellSans.ttf"

F = 4  # supersampling factor used by every generator

WHITE = (255, 255, 255, 255)        # hour numerals
INK = (242, 239, 233, 255)          # hands (ecru, matches baked blades)
BLACK = (0, 0, 0, 255)              # dial fill — pure black, OLED pixels off
DATE_GRAY = (131, 129, 124, 255)    # date ring digits
DAY_GRAY = (146, 144, 138, 255)     # weekday initials
DAY_ORANGE = (255, 150, 19, 255)    # weekend initials
OVAL_ORANGE = (243, 146, 30, 255)   # hand-drawn oval around today's date
BATT_GRAY = (146, 144, 139, 255)    # battery gauge arc segments
BATT_RED = (204, 52, 36, 255)       # battery empty end
BATT_BLUE = (64, 110, 194, 255)     # battery full end
DAY_ARC_ORANGE = (249, 144, 20, 255)  # weekend day-gauge arcs
DAY_ARC_GRAY = (151, 149, 142, 255)   # weekday day-gauge arcs

HOUR_SIZE = 110   # cap height 80px at 4x == the original Arial 26 numerals
DATE_SIZE = 40    # cap height 28px at 4x == the original 11px ring digits
DAY_SIZE = 45     # cap height 32px at 4x == the original 9px bold initials


def _font(size):
    return ImageFont.truetype(str(SHANTELL), size)


def glyph_tile(text, size, fill, rot_deg, out_px=None):
    """Text drawn at 4x on a 256px tile, optionally rotated about its center
    (tops-out convention: rotate clockwise by the placement angle)."""
    T = 64 * F
    t = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    ImageDraw.Draw(t).text((T / 2, T / 2), text, font=_font(size), fill=fill, anchor="mm")
    if rot_deg % 360:
        t = t.rotate(-rot_deg, resample=Image.BICUBIC, center=(T / 2, T / 2))
    if out_px:
        t = t.resize((out_px, out_px), Image.LANCZOS)
    return t


def polar(c, r, ang):
    a = math.radians(ang)
    return c + r * math.sin(a), c - r * math.cos(a)


def arc_round(d, c, r, w, a0, a1, fill):
    """Arc from a0 to a1 (deg from top, clockwise) at radius r, thickness w,
    with round caps — drawn as overlapping dots so the ends are rounded."""
    n = max(2, int((a1 - a0) * 2))
    for i in range(n + 1):
        x, y = polar(c, r, a0 + (a1 - a0) * i / n)
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=fill)


def gen_date_ring():
    """31 digits, tops-out, digit d at d*(360/31) clockwise from 12; the XML
    rotates the ring by 360 - DAY*11.612903 so today lands upright on top."""
    W = 450
    img = Image.new("RGBA", (W * F, W * F), (0, 0, 0, 0))
    cc = W * F / 2
    step = 360 / 31
    for day in range(1, 32):
        a = day * step
        x, y = polar(cc, 212 * F, a)
        t = glyph_tile(str(day), DATE_SIZE, DATE_GRAY, a)
        img.alpha_composite(t, (round(x - 32 * F), round(y - 32 * F)))
    return img.resize((W, W), Image.LANCZOS)


def gen_day_hand():
    """Miniature of hand_gauge at the same taper rate: w2 tip -> ~w5.5 at the
    pivot, constant to a rounded butt. Tip r=28 stays inside the letter ring."""
    W, H = 16, 56  # pivot at (8, 28)
    img = Image.new("RGBA", (W * F, H * F), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W * F / 2
    tip_y, pivot_y, butt_y = 3 * F, 28 * F, 36 * F
    hw_tip, hw_pivot = 1.0 * F, 2.75 * F
    d.polygon([(cx - hw_tip, tip_y), (cx + hw_tip, tip_y),
               (cx + hw_pivot, pivot_y), (cx + hw_pivot, butt_y),
               (cx - hw_pivot, butt_y), (cx - hw_pivot, pivot_y)], fill=INK)
    d.ellipse([cx - hw_pivot, butt_y - hw_pivot, cx + hw_pivot, butt_y + hw_pivot], fill=INK)
    return img.resize((W, H), Image.LANCZOS)


def gen_date_oval():
    """Hand-drawn marker oval around today's date: wobbling radius, breathing
    stroke width, ~30 deg overshoot drifting outward so the ends don't retrace."""
    W, H = 52, 42
    img = Image.new("RGBA", (W * F, H * F), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = W * F / 2, H * F / 2
    rx, ry = 23 * F, 17.5 * F
    start = math.radians(-70)
    steps = 260
    for i in range(steps):
        t = i / steps
        th = start + t * math.radians(390)
        wob = 1 + 0.035 * math.sin(2 * th + 0.9) + 0.02 * math.sin(3 * th + 2.1)
        drift = 1 + 0.03 * t
        x = cx + rx * wob * drift * math.cos(th)
        y = cy + ry * wob * drift * math.sin(th)
        if t < 0.08:
            wdt = 1.2 + t / 0.08 * 1.0
        elif t > 0.93:
            wdt = 2.2 - (t - 0.93) / 0.07 * 1.2
        else:
            wdt = 2.2 + 0.5 * math.sin(4 * th + 1.3)
        r = wdt * F / 2 * 1.6
        d.ellipse([x - r, y - r, x + r, y + r], fill=OVAL_ORANGE)
    return img.resize((W, H), Image.LANCZOS)


def gen_burgee():
    """The IV burgee, monochrome ecru, from the logo.svg geometry (512 space:
    pennant M96,116 L416,116 L256,396 Z stroked 36 round; V border and serif I
    cut out). Rendered at 4x, returned as a ~20x18 RGBA tile."""
    OUT_W = 20
    sc = OUT_W * F / 356.0                     # SVG content bbox is 356x316
    ox, oy = -78 * sc, -98 * sc                # bbox origin -> tile origin
    tw, th = OUT_W * F, round(316 * sc)

    def pt(x, y):
        return (x * sc + ox, y * sc + oy)

    def stroke_path(draw, pts, width, fill, closed=False):
        w = width * sc
        seq = pts + [pts[0]] if closed else pts
        for a, b in zip(seq, seq[1:]):
            draw.line([a, b], fill=fill, width=round(w))
        for x, y in seq:
            draw.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=fill)

    tri = [pt(96, 116), pt(416, 116), pt(256, 396)]
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.polygon(tri, fill=INK)
    stroke_path(d, tri, 36, INK, closed=True)

    cut = Image.new("L", (tw, th), 0)
    dc = ImageDraw.Draw(cut)
    stroke_path(dc, [pt(96, 116), pt(256, 396), pt(416, 116)], 36, 255)
    i_path = [pt(176, 100), pt(336, 100), pt(336, 134), pt(278, 134), pt(278, 278),
              pt(304, 278), pt(304, 312), pt(208, 312), pt(208, 278), pt(234, 278),
              pt(234, 134), pt(176, 134)]
    dc.polygon(i_path, fill=255)
    tile.putalpha(ImageChops.subtract(tile.getchannel("A"), cut))
    return tile.resize((OUT_W, round(th / F)), Image.LANCZOS)


def gen_hour_dial():
    """Fully generated: black disc, 11 upright numerals at r=92, burgee at 12.
    The burgee's inner edge sits near r=78, clear of the hand tip at r=70.5."""
    S = 225
    disc = Image.new("RGBA", (S * F, S * F), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse([0, 0, S * F - 1, S * F - 1], fill=BLACK)
    im = disc.resize((S, S), Image.LANCZOS)
    c = S / 2
    for h in range(1, 12):
        x, y = polar(c, 92, h * 30)
        im.alpha_composite(glyph_tile(str(h), HOUR_SIZE, WHITE, 0, out_px=64),
                           (round(x - 32), round(y - 32)))
    b = gen_burgee()
    im.alpha_composite(b, (round(c - b.width / 2), 17))
    return im


def gen_batt_dial():
    """BB2-style battery gauge (132): five arc segments every 72deg — gray, gray,
    red, blue, gray — with a white charge bolt in the bottom gap. Opaque black
    disc so satellites occlude seamlessly."""
    S = 132
    im = Image.new("RGBA", (S * F, S * F), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, S * F - 1, S * F - 1], fill=BLACK)
    c = S * F / 2
    for k, col in enumerate([BATT_GRAY, BATT_GRAY, BATT_RED, BATT_BLUE, BATT_GRAY]):
        ctr = k * 72
        arc_round(d, c, 51 * F, 4 * F, ctr - 29, ctr + 29, col)
    bx, by = polar(c, 51 * F, 180)          # charge bolt in the bottom gap
    bolt = [(-2.5, -6), (1.5, -6), (-0.5, -0.5), (3, -0.5), (-2, 7), (-0.5, 0.5), (-3.5, 0.5)]
    d.polygon([(bx + px * F, by + py * F) for px, py in bolt], fill=WHITE)
    return im.resize((S, S), Image.LANCZOS)


def gen_day_dial():
    """Day-of-week gauge (132): seven arc segments (weekend S's orange, weekdays
    gray) with upright Shantell initials at r=40, on an opaque black disc."""
    S = 132
    im = Image.new("RGBA", (S * F, S * F), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, S * F - 1, S * F - 1], fill=BLACK)
    c = S * F / 2
    for i, day in enumerate(["S", "M", "T", "W", "T", "F", "S"]):
        ctr = (i + 0.5) * 360 / 7
        weekend = i in (0, 6)
        arc_round(d, c, 51 * F, 2 * F, ctr - 20, ctr + 20,
                  DAY_ARC_ORANGE if weekend else DAY_ARC_GRAY)
        x, y = polar(c, 40 * F, ctr)
        tile = glyph_tile(day, DAY_SIZE, DAY_ORANGE if weekend else DAY_GRAY, 0)
        im.alpha_composite(tile, (round(x - 32 * F), round(y - 32 * F)))
    return im.resize((S, S), Image.LANCZOS)


def gen_font_subset():
    """Digits + SMTWF subset for the WFF PartText elements (active date, today's
    initial). Rendering matches the baked art: same file, same default instance."""
    import os
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")  # deterministic head.modified
    from fontTools import subset
    from fontTools.varLib.instancer import instantiateVariableFont
    opts = subset.Options()
    sub = subset.Subsetter(opts)
    font = subset.load_font(str(SHANTELL), opts)
    sub.populate(text="0123456789SMTWF")
    sub.subset(font)
    # We only ever render the default instance, so pin the variation axes and drop
    # the variable-font machinery (fvar/gvar/…): ~34 KB smaller, no visual change.
    if "fvar" in font:
        instantiateVariableFont(
            font, {a.axisTag: a.defaultValue for a in font["fvar"].axes}, inplace=True
        )
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def png_bytes(img):
    """Canonical PNG encoding, used for both writing and byte-exact --check.
    PIL's default PNG save is deterministic run-to-run, so re-running the
    generator reproduces committed bytes exactly."""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def build_all():
    # Every asset is a pure function of code + the source font/logo, so the whole
    # set reproduces byte-for-byte and --check verifies exact bytes.
    return {
        "date_ring.png": gen_date_ring(),
        "day_hand.png": gen_day_hand(),
        "date_oval.png": gen_date_oval(),
        "hour_dial.png": gen_hour_dial(),
        "day_dial.png": gen_day_dial(),
        "batt_dial.png": gen_batt_dial(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report drift, write nothing")
    args = ap.parse_args()

    assets = build_all()
    font_bytes = gen_font_subset()
    drift = 0

    for name, img in assets.items():
        path = DRAW / name
        gen = png_bytes(img)
        if args.check:
            if path.read_bytes() == gen:
                print(f"{name}: exact match")
            else:
                # bytes differ — say whether it's pixel drift or only re-encoding
                cur = Image.open(path).convert("RGBA")
                bbox = ImageChops.difference(cur, img).getbbox() if cur.size == img.size else True
                kind = "PIXEL DRIFT" if bbox else "byte drift (re-encode only)"
                print(f"{name}: {kind}")
                drift += 1
        else:
            path.write_bytes(gen)
            print(f"wrote {path.relative_to(ROOT)}")

    if args.check:
        cur = RES_FONT.read_bytes()
        if cur == font_bytes:
            print("shantell.ttf: exact match")
        else:
            print(f"shantell.ttf: DRIFT ({len(cur)} vs {len(font_bytes)} bytes)")
            drift += 1
        sys.exit(1 if drift else 0)
    else:
        RES_FONT.write_bytes(font_bytes)
        print(f"wrote {RES_FONT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
