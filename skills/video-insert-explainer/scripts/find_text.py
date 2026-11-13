"""Find on-screen occurrences of words: sample frames, OCR them with macOS Vision, group hits into runs.

usage: python3 find_text.py <video> <outdir> --words 回覧板,回覧,かいらん [--start 0 --end END] [--fps 10]

- extracts frames at --fps (10 = every 0.1 s; 2 fps misses captions shown for ~0.2 s) at 1920x1080,
- runs scripts/ocr_frames.swift on them (needs Xcode command line tools: `swift`),
- writes ocr.tsv (every recognized text with its box) and hits.tsv: one row per run of consecutive frames
  containing any of --words, with first/last sampled time and the union box (1080p pixels).
The sampled times are only a guide: measure the exact first/last frame on the source's own frame grid with
find_cut.py --band around each run before writing plate times. OCR misreads stylized text - also search
partial spellings (e.g. two of the three characters) and the reading in kana.
"""

import argparse
import os
import subprocess

from common import ff, run

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("outdir")
    ap.add_argument("--words", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--langs", default="ja-JP,en-US")
    a = ap.parse_args()
    frames = os.path.join(a.outdir, "frames")
    os.makedirs(frames, exist_ok=True)
    cmd = [ff(), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(a.start)]
    if a.end is not None:
        cmd += ["-t", str(a.end - a.start)]
    run(cmd + ["-i", a.video, "-vf", f"fps={a.fps},scale=1920:1080", "-q:v", "3", os.path.join(frames, "f_%06d.jpg")])
    out = subprocess.run(["swift", os.path.join(HERE, "ocr_frames.swift"), frames, a.langs], check=True,
                         capture_output=True, text=True).stdout
    with open(os.path.join(a.outdir, "ocr.tsv"), "w", encoding="utf-8") as fh:
        fh.write(out)
    words = a.words.split(",")
    hits = {}
    for line in out.splitlines():
        f, text, x, y, w, h = line.split("\t")
        if any(wd in text for wd in words):
            k = int(f[2:8])
            hits.setdefault(k, []).append((text, int(x), int(y), int(w), int(h)))
    rows, run_ = [], []
    for k in sorted(hits):
        if run_ and k != run_[-1] + 1:
            rows.append(run_)
            run_ = []
        run_.append(k)
    if run_:
        rows.append(run_)
    t = lambda k: a.start + (k - 1) / a.fps  # noqa: E731
    lines = ["first_s\tlast_s\tx0\ty0\tx1\ty1\ttext"]
    for r in rows:
        boxes = [b for k in r for b in hits[k]]
        x0, y0 = min(b[1] for b in boxes), min(b[2] for b in boxes)
        x1, y1 = max(b[1] + b[3] for b in boxes), max(b[2] + b[4] for b in boxes)
        lines.append(f"{t(r[0]):.2f}\t{t(r[-1]):.2f}\t{x0}\t{y0}\t{x1}\t{y1}\t{boxes[0][0]}")
    with open(os.path.join(a.outdir, "hits.tsv"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
