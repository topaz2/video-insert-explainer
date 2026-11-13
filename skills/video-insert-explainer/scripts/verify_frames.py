"""Pull labeled check frames from the final mp4 by frame number and tile them into contact sheets.

usage: python3 verify_frames.py <project.json> <final.mp4> <outdir>

Config "checks": [{"group": "...", "picks": [["o"|"T", seconds, "label"], ...]}, ...]
  "o" = source-video time (before or after the insert), "T" = insert time. Frame numbers come from
  Project.out_frame, so a check can never land on the wrong side of the cut.
For every plate and replacement, pick the frame just before, the first, middle and last frame, and the frame
just after; for zooming text also every frame of the zoom.
"""

import os
import sys

from PIL import Image, ImageDraw

from common import Project, ff, font, run


def main():
    pj = Project(sys.argv[1])
    src, outdir = sys.argv[2:4]
    os.makedirs(outdir, exist_ok=True)
    checks = pj.get("checks", [])
    frames = sorted({pj.out_frame(a, t) for g in checks for a, t, _ in g["picks"]})
    sel = "+".join(f"eq(n\\,{n})" for n in frames)
    run([ff(), "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", f"select='{sel}'", "-fps_mode", "passthrough",
         os.path.join(outdir, "f_%04d.png")])
    path_of = {n: os.path.join(outdir, f"f_{i + 1:04d}.png") for i, n in enumerate(frames)}
    f = font(pj, 6, 22)
    index = []
    for gi, g in enumerate(checks, start=1):
        tiles = []
        for axis, t, label in g["picks"]:
            n = pj.out_frame(axis, t)
            im = Image.open(path_of[n]).convert("RGB").resize((640, 360))
            text = f"out {n / pj.fps:.3f}s ({'src' if axis == 'o' else 'T'} {t:.3f}) {label}"
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, 14 + f.getlength(text), 30), fill="black")
            d.text((6, 3), text, font=f, fill="yellow")
            tiles.append(im)
            index.append(f'{g["group"]}\t{label}\t{axis} {t:.3f}\tframe {n}\t{path_of[n]}')
        cols = 3 if len(tiles) > 4 else 2
        sheet = Image.new("RGB", (cols * 644, ((len(tiles) + cols - 1) // cols) * 364), "white")
        for i, im in enumerate(tiles):
            sheet.paste(im, ((i % cols) * 644, (i // cols) * 364))
        name = os.path.join(outdir, f"sheet_{gi:02d}.png")
        sheet.save(name)
        index.append(f'== {g["group"]}: {name}')
    with open(os.path.join(outdir, "index.tsv"), "w") as fh:
        fh.write("\n".join(index) + "\n")
    print("\n".join(index))


if __name__ == "__main__":
    main()
