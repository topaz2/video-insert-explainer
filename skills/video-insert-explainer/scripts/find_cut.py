"""Locate a cut point frame-accurately: a 0.1 s contact sheet, an optional caption-band stack, and an RMS table.

usage: python3 find_cut.py <video> <start> <end> <outdir> [--band x,y,w,h] [--step 0.1] [--rms-ms 50]

- sheet.jpg: one tile per step (time printed on each), to see the shot change and when captions appear.
- band.png: the caption band (--band, 1080p pixels) of every frame in [start, end] at the video's own frame rate,
  stacked, to find the last frame without the next caption.
- rms.tsv / stdout: RMS in dBFS per --rms-ms window; a cut belongs in a valley between lines (speech sits
  ~20 dB above the valley), and the freeze frame is the last frame before the next caption appears.
"""

import argparse
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw

from common import ff, font, run


def frame_at(video, t, out, vf=None):
    cmd = [ff(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.4f}", "-i", video, "-frames:v", "1"]
    if vf:
        cmd += ["-vf", vf]
    run(cmd + [out])
    return Image.open(out).convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("outdir")
    ap.add_argument("--band", default="")
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--rms-ms", type=int, default=50)
    ap.add_argument("--font", default="/System/Library/Fonts/ヒラギノ角ゴシック W{}.ttc")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    tmp = os.path.join(a.outdir, "_f.png")
    f = font(a.font, 6, 20)
    times = [round(a.start + i * a.step, 3) for i in range(int(round((a.end - a.start) / a.step)) + 1)]
    tiles = []
    for t in times:
        im = frame_at(a.video, t, tmp, "scale=384:216")
        ImageDraw.Draw(im).text((4, 2), f"{t:.2f}", font=f, fill="yellow", stroke_width=2, stroke_fill="black")
        tiles.append(im)
    cols = 10
    sheet = Image.new("RGB", (cols * 388, ((len(tiles) + cols - 1) // cols) * 220), "white")
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * 388, (i // cols) * 220))
    sheet.save(os.path.join(a.outdir, "sheet.jpg"), quality=85)
    if a.band:
        x, y, w, h = map(int, a.band.split(","))
        fps = subprocess.run([ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                              "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip()
        num, den = map(int, fps.split("/"))
        rate = num / den
        rows = []
        k = int(np.ceil(a.start * rate))
        while k / rate <= a.end:
            im = frame_at(a.video, k / rate + 0.25 / rate, tmp, f"scale=1920:1080,crop={w}:{h}:{x}:{y}")
            ImageDraw.Draw(im).text((4, 2), f"{k / rate:.3f}", font=f, fill="yellow", stroke_width=2, stroke_fill="black")
            rows.append(im)
            k += 1
        stack = Image.new("RGB", (w, len(rows) * (h + 4)), "white")
        for i, im in enumerate(rows):
            stack.paste(im, (0, i * (h + 4)))
        stack.save(os.path.join(a.outdir, "band.png"))
    os.unlink(tmp)
    sr = 48000
    raw = subprocess.run([ff(), "-hide_banner", "-loglevel", "error", "-ss", str(a.start), "-t", str(a.end - a.start), "-i", a.video,
                          "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    y = np.frombuffer(raw, np.float32)
    win = sr * a.rms_ms // 1000
    n = len(y) // win
    db = 20 * np.log10(np.sqrt((y[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-12)
    lines = [f"{a.start + i * a.rms_ms / 1000:.3f}\t{v:.1f}" for i, v in enumerate(db)]
    with open(os.path.join(a.outdir, "rms.tsv"), "w") as fh:
        fh.write("time\tdBFS\n" + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
