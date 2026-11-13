"""Mechanical QA of the final mp4: frame count, A/V offset against the source, loudness, black/frozen stretches.

usage: python3 check_output.py <project.json> <final.mp4> [--sync 30,200,400] [--dialogue START,DUR]

- frames: output frame count must equal base_frames + insert_frames.
- sync: for each source time t (seconds, outside the insert), cross-correlates 2 s of source audio with the same
  stretch of the output (mapped across the insert) and prints the lag in ms; anything but ~0 is a drift.
- loudness: whole output, the insert alone, and a source dialogue window (--dialogue) for comparison.
- blackdetect / freezedetect stretches are printed with their output times; compare them with the source
  before calling one a defect (the source may contain them too, and a held slide is frozen by design).
Pick sync times inside speech or other non-periodic sound: a steady tone correlates at many lags and
reports a false offset. Exits 1 if the frame count or any sync lag (> 1 frame) is off.
"""

import argparse
import re
import subprocess

import numpy as np

from common import Project, ff
from loudness import measure


def pcm(path, start, dur, sr=16000):
    raw = subprocess.run([ff(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.4f}", "-t", f"{dur:.4f}", "-i", path,
                          "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def lag_ms(a, b, sr=16000, max_ms=200):
    m = int(sr * max_ms / 1000)
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = min(len(a), len(b)) - 2 * m
    best = max(range(-m, m + 1), key=lambda k: float(np.dot(a[m: m + n], b[m + k: m + k + n])))
    return best * 1000 / sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("final")
    ap.add_argument("--sync", default="")
    ap.add_argument("--dialogue", default="")
    a = ap.parse_args()
    pj = Project(a.project)
    bad = 0
    got = int(subprocess.run([ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                              "stream=nb_read_packets", "-of", "csv=p=0", a.final], capture_output=True, text=True).stdout.strip())
    want = pj.base_frames + pj.insert_frames
    print(f"frames {got} (expected {want})", "OK" if got == want else "NG")
    bad += got != want
    ins0 = pj.cut_frame / pj.fps
    ins_len = pj.insert_frames / pj.fps
    for tok in filter(None, a.sync.split(",")):
        t = float(tok)
        out_t = t if t < ins0 else t + ins_len
        lag = lag_ms(pcm(pj.base, t, 2.0), pcm(a.final, out_t, 2.0))
        ok = abs(lag) <= 1000 / pj.fps
        bad += not ok
        print(f"sync src {t:.2f}s -> out {out_t:.2f}s: lag {lag:+.1f} ms", "OK" if ok else "NG")
    print("loudness whole", measure(a.final))
    print("loudness insert", measure(a.final, ins0, ins_len))
    if a.dialogue:
        s, d = map(float, a.dialogue.split(","))
        print(f"loudness source dialogue {s}+{d}", measure(pj.base, s, d))
    err = subprocess.run([ff(), "-hide_banner", "-nostats", "-i", a.final, "-vf", "blackdetect=d=0.1:pix_th=0.05,freezedetect=n=0.003:d=0.5",
                          "-an", "-f", "null", "-"], capture_output=True, text=True).stderr
    for m in re.finditer(r"(black_start:\S+ black_end:\S+|freeze_start: \S+|freeze_end: \S+)", err):
        print("detect", m.group(1))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
