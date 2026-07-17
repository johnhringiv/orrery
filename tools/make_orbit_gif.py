"""Renders a looping time-lapse of the face by stepping a rooted Wear OS
emulator through fake wall-clock time and screencapping each step.

Needs: a *rootable* (AOSP "android-wear", not "-signed") emulator running with
the face installed and set, `adb root` already applied, auto time off:
    adb shell "settings put global auto_time 0; svc power stayon true"

Usage:
    py tools/make_orbit_gif.py [--start 10:00] [--hours 12] [--step-min 3]
                               [--fps 15] [--scale 1.0] [--crossfade 0]
                               [--quality 80] [--codec h264] [--out orbit.webp]

Output format follows the --out extension:
  .webp  animated, autoplays and loops inline on GitHub (recommended there)
  .gif   animated, universal but largest
  .mp4   video (--codec h264 or av1, needs ffmpeg) — a fraction of the .webp
         size and ideal for a website <video autoplay loop muted playsinline>,
         but not embeddable in a GitHub README

The emulator's date is pinned to today; only the clock moves, so the date ring
and day gauge hold still while the orbits sweep. Capture is exclusive of the
end time, so the frame that would duplicate the start is never taken.

Two loop recipes:

  Compact single orbit (1h). Satellites and minute hand wrap cleanly, but the
  hour hand creeps 30deg over the hour and would snap back at the seam; a short
  --crossfade blends that snap into a dissolve (only the hour hand differs
  end-to-start, so it reads as that one blade morphing, not a whole-frame blur):
      --start 10:00 --hours 1 --step-min 0.5 --fps 10 --crossfade 4 --out orbit.webp

  Full day (12h), naturally seamless — no crossfade, no reset. Over 12 hours the
  hour hand completes exactly one lap and every element returns to its start, so
  the loop closes on itself. Costs 12x the frames for 12 orbits:
      --start 10:00 --hours 12 --step-min 0.5 --fps 10 --out orbit-12h.webp

  The 12h loop is ~9 MB as .webp but ~1-2 MB as .mp4, so for a website render it
  as video (same flags, --codec av1 or h264, .mp4 output):
      --start 10:00 --hours 12 --step-min 0.5 --fps 10 --codec av1 --out orbit-12h.mp4
"""
import argparse
import datetime as dt
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ADB = os.environ.get("ADB", os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"))
SERIAL = os.environ.get("ADB_SERIAL", "emulator-5554")


def adb(*args, binary=False):
    r = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"adb {' '.join(args[:3])}... failed: {r.stderr.decode(errors='replace')[:200]}")
    return r.stdout if binary else r.stdout.decode(errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="10:00")
    ap.add_argument("--hours", type=float, default=12.0)
    ap.add_argument("--step-min", type=float, default=3.0)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--crossfade", type=int, default=0,
                    help="blend N frames across the seam (softens the 1h hour-hand snap; a 12h loop needs none)")
    ap.add_argument("--quality", type=int, default=80, help="WebP quality 0-100 (ignored for GIF/MP4)")
    ap.add_argument("--codec", choices=("h264", "av1"), default="h264",
                    help="video codec for .mp4 output (ignored otherwise)")
    ap.add_argument("--out", default="orbit.webp")
    args = ap.parse_args()

    ext = os.path.splitext(args.out)[1].lower()
    if ext not in (".webp", ".gif", ".mp4"):
        raise SystemExit(f"unsupported output extension {ext!r} — use .webp, .gif, or .mp4")

    from PIL import Image

    h, m = map(int, args.start.split(":"))
    today = dt.date.today()
    t = dt.datetime.combine(today, dt.time(h, m))
    end = t + dt.timedelta(hours=args.hours)
    step = dt.timedelta(minutes=args.step_min)

    frames = []
    n = 0
    # Exclusive of end: the end frame would duplicate the start and stutter the loop.
    total = int(round(args.hours * 60 / args.step_min))
    workdir = Path(tempfile.mkdtemp(prefix="orbit_frames_"))
    print(f"capturing {total} frames into {workdir}")

    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    while t < end:
        # toybox date: MMDDhhmmCCYY.ss — day stays fixed, only the clock moves
        stamp = t.strftime("%m%d%H%M%Y.%S")
        adb("shell", "date", stamp)
        png = adb("exec-out", "screencap", "-p", binary=True)
        frame = Image.open(io.BytesIO(png)).convert("RGB")
        if args.scale != 1.0:
            frame = frame.resize((round(frame.width * args.scale),) * 2, Image.LANCZOS)
        (workdir / f"f{n:04d}.png").write_bytes(png)
        frames.append(frame)
        n += 1
        if n % 20 == 0:
            print(f"  {n}/{total}  ({t.strftime('%H:%M')})")
        t += step

    # Crossfade the seam: blend the last real frame toward the first over N frames.
    if args.crossfade and len(frames) > 1:
        last, first = frames[-1], frames[0]
        frames += [Image.blend(last, first, k / (args.crossfade + 1))
                   for k in range(1, args.crossfade + 1)]

    print(f"assembling {ext[1:] + ' ' + args.codec if ext == '.mp4' else ext[1:]}...")
    if ext == ".mp4":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SystemExit("ffmpeg not found on PATH — needed for .mp4 output")
        codec = {
            "av1": ["-c:v", "libsvtav1", "-crf", "32", "-preset", "6"],
            "h264": ["-c:v", "libx264", "-crf", "23", "-preset", "slow"],
        }[args.codec]
        # Pipe the finished frames straight to ffmpeg (honors --scale and --crossfade).
        proc = subprocess.Popen(
            [ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe",
             "-framerate", str(args.fps), "-i", "-", *codec,
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", args.out],
            stdin=subprocess.PIPE,
        )
        for f in frames:
            f.save(proc.stdin, "PNG")
        proc.stdin.close()
        if proc.wait() != 0:
            raise SystemExit("ffmpeg encode failed")
    else:
        duration = round(1000 / args.fps)
        if ext == ".webp":
            # WebP does its own inter-frame compression, so pass the RGB frames as-is.
            frames[0].save(
                args.out, save_all=True, append_images=frames[1:],
                duration=duration, loop=0, lossless=False, quality=args.quality, method=6,
            )
        else:  # .gif
            pal = [f.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE) for f in frames]
            pal[0].save(
                args.out, save_all=True, append_images=pal[1:],
                duration=duration, loop=0, optimize=True,
            )

    total_frames = len(frames)
    size_mb = os.path.getsize(args.out) / 1e6
    print(f"wrote {args.out}: {total_frames} frames, {size_mb:.2f} MB, {total_frames / args.fps:.0f}s loop")


if __name__ == "__main__":
    main()
