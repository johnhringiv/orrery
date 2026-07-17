"""Regenerates Orrery's programmatic drawables and the embedded font subset.

Run from anywhere:  py tools/gen_assets.py [--check]

  (default)  writes assets into watchface/src/main/res/drawable/ and res/font/
  --check    regenerates in memory and reports any pixel/byte drift vs the repo

Fully generated here: hour_dial (disc + numerals + burgee), date_ring,
day_hand, date_oval, res/font/shantell.ttf. Patched in place here: day_dial
(letter layer), batt_dial (bolt brightness). Everything else in drawable/
(day/batt gauge bases, tick_ring, hands, preview) is baked art from the
prototyping phase — its history lives in git.

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


def patch_batt_dial(im):
    """Brightens the charge bolt to full white (baked at ~73 percent ecru).
    Touches only near-monochrome pixels inside the bolt's cell at the bottom."""
    im = im.convert("RGBA")
    px = im.load()
    for y in range(111, 127):
        for x in range(61, 72):
            r, g, b, a = px[x, y]
            if a > 20 and max(r, g, b) > 25 and abs(r - g) < 25 and abs(g - b) < 25:
                px[x, y] = (min(255, round(r * 255 / 185)),
                            min(255, round(g * 255 / 185)),
                            min(255, round(b * 255 / 185)), a)
    return im


def patch_day_dial(im):
    """Rewrites the 7 upright initials (r=40) on the baked gauge; weekend S's
    orange. Erase circles stay at r=6.5 to clear the arcs at r>=49."""
    im = im.convert("RGBA")
    d = ImageDraw.Draw(im)
    c = im.size[0] / 2
    days = ["S", "M", "T", "W", "T", "F", "S"]
    for i, day in enumerate(days):
        a = (i + 0.5) * 360 / 7
        x, y = polar(c, 40, a)
        d.ellipse([x - 6.5, y - 6.5, x + 6.5, y + 6.5], fill=BLACK)
        fill = DAY_ORANGE if i in (0, 6) else DAY_GRAY
        im.alpha_composite(glyph_tile(day, DAY_SIZE, fill, 0, out_px=64), (round(x - 32), round(y - 32)))
    return im


def gen_font_subset():
    """Digits + SMTWF subset for the WFF PartText elements (active date, today's
    initial). Rendering matches the baked art: same file, same default instance."""
    import os
    os.environ.setdefault("SOURCE_DATE_EPOCH", "0")  # deterministic head.modified
    from fontTools import subset
    opts = subset.Options()
    sub = subset.Subsetter(opts)
    font = subset.load_font(str(SHANTELL), opts)
    sub.populate(text="0123456789SMTWF")
    sub.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def build_all():
    return {
        "date_ring.png": gen_date_ring(),
        "day_hand.png": gen_day_hand(),
        "date_oval.png": gen_date_oval(),
        "hour_dial.png": gen_hour_dial(),
        "day_dial.png": patch_day_dial(Image.open(DRAW / "day_dial.png")),
        "batt_dial.png": patch_batt_dial(Image.open(DRAW / "batt_dial.png")),
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
        if args.check:
            cur = Image.open(path).convert("RGBA")
            if cur.size != img.size:
                print(f"{name}: SIZE DRIFT {cur.size} != {img.size}")
                drift += 1
                continue
            diff = ImageChops.difference(cur, img)
            bbox = diff.getbbox()
            if bbox is None:
                print(f"{name}: exact match")
            else:
                px = sum(1 for p in diff.getdata() if any(p))
                mx = max(max(p) for p in diff.getdata())
                print(f"{name}: DRIFT {px}px differ, max channel delta {mx}")
                drift += 1
        else:
            img.save(path)
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
