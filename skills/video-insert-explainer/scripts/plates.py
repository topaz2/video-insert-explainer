"""Cover plates for burned-in text on the SOURCE timeline: opaque Pillow PNGs + manifest.json.

usage: python3 plates.py <project.json> [out_dir]     (default out_dir: <work>/plates)

Config "plates": a list of
  static plate  {"id", "start", "end", "rect": [x0,y0,x1,y1], "color", "radius", "feather",
                 "text": {"runs": [[text, fill, stroke_fill|null], ...], "left", "top", "weight", "size", "stroke"}}
  staged plate  {"id", "text": {...without left/top/size}, "fill", "weight", "feather_ratio",
                 "stages": [{"t0","t1","left","top","size","rect","c0","c1","blur"}, ...]}
                 -> one PNG per stage plus one PNG per output frame between consecutive stages, with every value
                    interpolated linearly in time (for text that zooms with the picture).
start/end/t0/t1 are measured on the source frame grid (source.measured_fps); end = last frame still showing the
original text. manifest rows {"id","png","start","end"} cover output frames with start <= t < end.
"""

import json
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from common import Project, font, hexrgb
from textlib import canvas, draw_runs

EPS = 1e-4


def window(pj, start, end):
    """Measured [start, last frame shown] on the source grid -> [start, end) on the output grid."""
    half = 1 / pj.source_fps
    k0, k1 = round(start * pj.source_fps), round(end * pj.source_fps)
    return round(k0 * half - EPS, 4), round((k1 + 1) * half - EPS, 4)


def feather_outward(img, blur):
    """Soften only outward: the measured rectangle stays fully opaque so nothing underneath shows through."""
    if not blur:
        return img
    soft = img.filter(ImageFilter.GaussianBlur(blur))
    alpha = ImageChops.lighter(soft.getchannel("A"), img.getchannel("A"))
    rgb = Image.composite(img, soft, img.getchannel("A")).convert("RGB")
    rgb.putalpha(alpha)
    return rgb


def static_plate(pj, p):
    img = canvas()
    d = ImageDraw.Draw(img)
    rect, color = p["rect"], hexrgb(p.get("color", "#000000"))
    if p.get("radius"):
        d.rounded_rectangle(rect, p["radius"], fill=color)
    else:
        d.rectangle(rect, fill=color)
    img = feather_outward(img, p.get("feather", 0))
    t = p.get("text")
    if t:
        runs = [(r[0], hexrgb(r[1]), hexrgb(r[2]) if r[2] else None) for r in t["runs"]]
        draw_runs(img, runs, t["left"], t["top"], font(pj, t.get("weight", 6), t["size"]), stroke=t.get("stroke", 0))
    return img


def stage_frame(pj, p, st):
    img = canvas()
    d = ImageDraw.Draw(img)
    x1, y1, x2, y2 = (round(v) for v in st["rect"])
    c0, c1 = hexrgb(st["c0"]), hexrgb(st["c1"])
    for yy in range(y1, y2 + 1):  # vertical gradient matched to the measured background
        r = (yy - y1) / max(1, y2 - y1)
        d.line((x1, yy, x2, yy), fill=tuple(round(c0[i] * (1 - r) + c1[i] * r) for i in range(3)) + (255,))
    img = feather_outward(img, st["size"] * p.get("feather_ratio", 0.13))
    text = canvas()
    draw_runs(text, [(p["text"]["text"], hexrgb(p["fill"]), None)], st["left"], st["top"],
              font(pj, p.get("weight", 6), round(st["size"], 1)))
    img.alpha_composite(text.filter(ImageFilter.GaussianBlur(st.get("blur", 0))))
    return img


def lerp_stage(a, b, r):
    mix = lambda u, v: u + (v - u) * r  # noqa: E731
    col = lambda h0, h1: "#%02X%02X%02X" % tuple(round(mix(x, y)) for x, y in zip(hexrgb(h0)[:3], hexrgb(h1)[:3]))  # noqa: E731
    return dict(left=mix(a["left"], b["left"]), top=mix(a["top"], b["top"]), size=mix(a["size"], b["size"]),
                rect=tuple(mix(u, v) for u, v in zip(a["rect"], b["rect"])), c0=col(a["c0"], b["c0"]),
                c1=col(a["c1"], b["c1"]), blur=mix(a.get("blur", 0), b.get("blur", 0)))


def main():
    pj = Project(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else pj.p(pj.get("work_dir", "work") + "/plates")
    os.makedirs(out, exist_ok=True)
    rows, fps = [], pj.fps

    def save(pid, img, start, end):
        path = os.path.join(out, f"{pid}.png")
        img.save(path)
        rows.append({"id": pid, "png": path, "start": start, "end": end})

    for p in pj.get("plates", []):
        if "stages" not in p:
            save(p["id"], static_plate(pj, p), *window(pj, p["start"], p["end"]))
            continue
        st = p["stages"]
        for i, s in enumerate(st):
            save(f'{p["id"]}_{i}', stage_frame(pj, p, s), *window(pj, s["t0"], s["t1"]))
        for i in range(len(st) - 1):
            a, b = st[i], st[i + 1]
            lo, hi = window(pj, a["t0"], a["t1"])[1], window(pj, b["t0"], b["t1"])[0]
            for k in range(int(a["t1"] * fps) + 1, int(b["t0"] * fps) + 1):
                t = k / fps
                if not lo <= t < hi:
                    continue
                r = (t - a["t1"]) / (b["t0"] - a["t1"])
                save(f'{p["id"]}_{i}to{i + 1}_{k}', stage_frame(pj, p, lerp_stage(a, b, r)),
                     round(t - 1 / (2 * fps), 4), round(t + 1 / (2 * fps), 4))
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(f'{r["id"]:<16}{r["start"]:>10.4f}{r["end"]:>10.4f}  {r["png"]}')


if __name__ == "__main__":
    main()
