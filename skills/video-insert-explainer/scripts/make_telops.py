"""Subtitle, interjection and heading telops for the insert as 1920x1080 PNGs + manifest.json (insert time T).

usage: python3 make_telops.py <project.json>

Reads config "narration.timeline", "narration.subtitles" ({id: "line 1／line 2"}; ／ = forced break, otherwise
wrapped at style.max_chars after 、) and the resolved events ("heading", "interjections").
A subtitle starts at the voice onset of its clip (timeline "voice", floored to the frame), not at the clip start:
TTS clips carry up to ~0.9 s of near-silence at the head, so clip-start subtitles run ahead of the voice.
"""

import json
import math
import os
import sys

from PIL import Image

from common import Project, font, hexrgb
from textlib import MAX_CHARS, telop, wrap


def floor_frame(t, fps):
    # truncate, not round: round(614/30, 4) lands after frame 614 itself and hides the first frame
    return math.floor(math.floor(t * fps + 1e-6) / fps * 1e4) / 1e4


def main():
    pj = Project(sys.argv[1])
    st = pj.get("style", {})
    out = pj.p(pj.get("work_dir", "work") + "/telops")
    os.makedirs(out, exist_ok=True)
    tl = json.load(open(pj.p(pj.get("narration.timeline")), encoding="utf-8"))
    subs = json.load(open(pj.p(pj.get("narration.subtitles")), encoding="utf-8"))
    ev = pj.events
    max_chars = st.get("max_chars", MAX_CHARS)
    sub_font = font(pj, st.get("sub_weight", 6), st.get("sub_size", 44))
    box = dict(fill=(0, 0, 0, round(255 * st.get("sub_box_alpha", 0.6))), radius=12, pad=16)
    gap = st.get("line_gap", 1.40)
    rows, problems = [], []

    def save(rid, img, start, end, lines, fade_in=0, fade_out=0):
        path = os.path.join(out, f"{rid}.png")
        img.save(path)
        rows.append({"id": rid, "png": path, "start": start, "end": end, "fade_in": fade_in, "fade_out": fade_out, "lines": lines})
        problems.extend(f"{rid}: {len(ln)} chars > {max_chars}: {ln}" for ln in lines if len(ln) > max_chars)

    h = ev.get("heading")
    if h:
        f = font(pj, st.get("head_weight", 8), st.get("head_size", 64))
        save("heading", telop([h["text"]], f, st.get("head_stroke", 6), top=st.get("head_top", 60)),
             h["start"], h["end"], [h["text"]], h.get("fade", 0.2), h.get("fade", 0.2))

    for seg in tl["segs"]:
        text = subs.get(seg["id"])
        if text is None:
            problems.append(f'{seg["id"]}: no subtitle text')
            continue
        lines = [s.strip() for s in text.split("／")] if "／" in text else wrap(text, max_chars)
        img = telop(lines, sub_font, st.get("sub_stroke", 5), bottom=st.get("sub_bottom", 1040), box=box, line_gap=gap)
        save(seg["id"], img, floor_frame(seg.get("voice", seg["start"]), pj.fps), seg["end"], lines)

    for i, ij in enumerate(ev.get("interjections", [])):
        pip = Image.open(pj.p(ij["pip"]))
        x, y = ev.get("pip_pos", [1500, 620])
        img = telop([ij["text"]], sub_font, st.get("sub_stroke", 5), fill=hexrgb(ij.get("color", "#8FD694")),
                    center_x=x + pip.width / 2, bottom=y - 10, box=box)
        save(f"interjection_{i}", img, ij["t"], round(ij["t"] + ij["dur"], 3), [ij["text"]])

    rows.sort(key=lambda r: r["start"])
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(f'{r["id"]:<16}{r["start"]:8.2f}{r["end"]:8.2f}  ' + " / ".join(r["lines"]))
    for p in problems:
        print("WARNING", p)


if __name__ == "__main__":
    main()
