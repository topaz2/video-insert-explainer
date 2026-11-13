"""Build a whole-line replacement on the source timeline: the new line over the source's accompaniment.

usage: python3 line_replace.py <video> <no_vocals.wav> <vocals.wav> <new_line.wav> <out.wav>
                               --stem-start S --context A B --line L0 L1

When the replaced word does not fit its slot (or a shouted line loses intelligibility when only the word is
swapped), regenerate the whole line with the same voice and lay it over the accompaniment.
- <no_vocals.wav> / <vocals.wav>: stems of a source excerpt starting at --stem-start seconds, e.g. from
  `python -m demucs --two-stems vocals -n htdemucs_ft <excerpt.wav>`.
- --context A B: the stretch written to <out.wav> (source audio around the line, for listening and for
  audio.replacements {"type": "line", "start": A}).
- --line L0 L1: the source line being replaced; the source is swapped for the accompaniment over it with
  30 ms cross-fades, the new line is trimmed, sped/slowed within 1/1.1..1.1 to the line length, and leveled to
  the original vocal's speech RMS. The video is not touched, so lips may drift by a few frames - check by eye.
"""

import argparse
import subprocess

import librosa
import numpy as np
import soundfile as sf

from common import ff

SR = 48000


def read(path, start=None, dur=None):
    cmd = [ff(), "-hide_banner", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    raw = subprocess.run(cmd + ["-i", path, "-vn", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def tempo(x, r):
    p = subprocess.run([ff(), "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
                        "-af", f"atempo={r:.4f}", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"], input=x.tobytes(), check=True, capture_output=True)
    return np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()


def speech_db(x):
    m = x.mean(axis=1)
    s = np.concatenate([m[a:b] for a, b in librosa.effects.split(m, top_db=35)])
    return 20 * np.log10(np.sqrt((s ** 2).mean()) + 1e-12)


def fade(n, up):
    r = np.linspace(0, 1, n, dtype=np.float32)[:, None]
    return r if up else 1 - r


def main():
    ap = argparse.ArgumentParser()
    for k in ("video", "no_vocals", "vocals", "new_line", "out"):
        ap.add_argument(k)
    ap.add_argument("--stem-start", type=float, required=True)
    ap.add_argument("--context", nargs=2, type=float, required=True)
    ap.add_argument("--line", nargs=2, type=float, required=True)
    a = ap.parse_args()
    c0, c1 = a.context
    l0, l1 = a.line
    n = int(round((c1 - c0) * SR))
    orig = read(a.video, c0, c1 - c0 + 0.5)[:n]
    acc = read(a.no_vocals, c0 - a.stem_start, c1 - c0 + 0.5)
    voc = read(a.vocals, c0 - a.stem_start, c1 - c0 + 0.5)
    acc = np.concatenate([acc, np.zeros((max(0, n - len(acc)), 2), np.float32)])[:n]
    at = lambda t: int(round((t - c0) * SR))  # noqa: E731
    v = read(a.new_line)
    iv = librosa.effects.split(v.mean(axis=1), top_db=35)
    pad = int(0.02 * SR)
    v = v[max(0, iv[0][0] - pad): min(len(v), iv[-1][1] + pad)]
    r = min(1.1, max(1 / 1.1, (len(v) / SR) / (l1 - l0)))
    if abs(r - 1) > 1e-3:
        v = tempo(v, r)
    v *= 10 ** ((speech_db(voc[at(l0): at(l1)]) - speech_db(v)) / 20)
    xf = int(0.03 * SR)
    s, e = at(l0), max(at(l1), at(l0) + len(v))
    out = orig.copy()
    out[s - xf // 2: s + xf // 2] = orig[s - xf // 2: s + xf // 2] * fade(xf, False) + acc[s - xf // 2: s + xf // 2] * fade(xf, True)
    out[s + xf // 2: e - xf // 2] = acc[s + xf // 2: e - xf // 2]
    out[e - xf // 2: e + xf // 2] = acc[e - xf // 2: e + xf // 2] * fade(xf, False) + orig[e - xf // 2: e + xf // 2] * fade(xf, True)
    end = min(len(out), s + len(v))
    out[s:end] += v[: end - s]
    sf.write(a.out, np.clip(out, -1, 1), SR, subtype="PCM_16")
    print(f"{a.out}\tcontext {c0}-{c1}\tline placed {l0:.2f}-{l0 + len(v) / SR:.2f}\ttempo {r:.3f}")


if __name__ == "__main__":
    main()
