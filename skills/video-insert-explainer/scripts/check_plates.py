"""Before/after strips for each plate group: render the group on a short cut of the work copy and put the source
and processed crops side by side for the frame before, first, middle, last and after (and every in-between
frame of staged plates).

usage: python3 check_plates.py <project.json> <group> ...     (group = plate id prefix)
writes <work>/plate_checks/check_<group>.png; the crop is the plates' own bounding box plus a margin.
"""

import json
import math
import os
import re
import sys

from PIL import Image, ImageDraw

from common import Project, ff, font, run
from filter_template import build


def grab(path, n, out):
    run([ff(), "-hide_banner", "-loglevel", "error", "-y", "-i", path, "-vf", f"select=eq(n\\,{n})",
         "-fps_mode", "passthrough", "-frames:v", "1", out])
    return Image.open(out).convert("RGB")


def main():
    pj = Project(sys.argv[1])
    work = pj.p(pj.get("work_dir", "work"))
    out_dir = os.path.join(work, "plate_checks")
    os.makedirs(out_dir, exist_ok=True)
    rows_all = json.load(open(os.path.join(work, "plates", "manifest.json"), encoding="utf-8"))
    fps, label_font = pj.fps, font(pj, 6, 18)
    for g in sys.argv[2:]:
        rows = [r for r in rows_all if r["id"] == g or r["id"].startswith(g + "_")]
        k_first = math.ceil(min(r["start"] for r in rows) * fps - 1e-6)
        k_last = math.ceil(max(r["end"] for r in rows) * fps - 1e-6) - 1
        cut0 = (k_first - 3) / fps
        inputs, script = build(rows, cut0, fps)
        sfile, clip = os.path.join(out_dir, f"filter_{g}.txt"), os.path.join(out_dir, f"check_{g}.mp4")
        with open(sfile, "w") as f:
            f.write(script + "\n")
        run([ff(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{cut0:.6f}", "-t", f"{(k_last - k_first + 7) / fps:.4f}",
             "-i", pj.base, *inputs, "-filter_complex_script", sfile, "-map", "[vout]", "-an",
             "-c:v", "libx264", "-crf", "14", "-preset", "fast", clip])
        box = None
        for r in rows:
            b = Image.open(r["png"]).getchannel("A").getbbox()
            if b:
                box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        m = 40
        box = (max(0, box[0] - m), max(0, box[1] - m), min(1920, box[2] + m), min(1080, box[3] + m))
        picks = {k_first - 1: "before", k_first: "first", (k_first + k_last) // 2: "middle", k_last: "last", k_last + 1: "after"}
        for r in rows:
            if re.search(r"_\d+to\d+_\d+$", r["id"]):
                picks.setdefault(round((r["start"] + r["end"]) / 2 * fps), "in transition")
        tiles = []
        for k in sorted(picks):
            new = grab(clip, k - (k_first - 3), os.path.join(out_dir, "_new.png"))
            orig = grab(pj.base, k, os.path.join(out_dir, "_orig.png"))
            w = box[2] - box[0]
            pair = Image.new("RGB", (w * 2 + 8, box[3] - box[1]), "white")
            pair.paste(orig.crop(box), (0, 0))
            pair.paste(new.crop(box), (w + 8, 0))
            d = ImageDraw.Draw(pair)
            label = f"{k / fps:.3f}s {picks[k]} (left=source right=plated)"
            d.rectangle((0, 0, 8 + label_font.getlength(label), 24), fill="black")
            d.text((4, 2), label, font=label_font, fill="yellow")
            tiles.append(pair)
        sheet = Image.new("RGB", (max(t.width for t in tiles), sum(t.height + 6 for t in tiles)), "white")
        y = 0
        for t in tiles:
            sheet.paste(t, (0, y))
            y += t.height + 6
        path = os.path.join(out_dir, f"check_{g}.png")
        sheet.save(path)
        print(g, f"frames {k_first}..{k_last}", path)
    for tmp in ("_new.png", "_orig.png"):
        p = os.path.join(out_dir, tmp)
        if os.path.exists(p):
            os.unlink(p)


if __name__ == "__main__":
    main()
