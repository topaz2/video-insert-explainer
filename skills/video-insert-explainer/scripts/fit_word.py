"""Fit a replacement word clip into the slot of the source word: trim silence, speed up within a cap, match level.

usage: python3 fit_word.py <raw.wav> <out.wav> --slot 0.60 --max-tempo 1.10
                           (--target-db -18.0 | --match <video> --range START END)

- trims leading/trailing silence (-45 dB), then atempo = max(1, length / slot), capped at --max-tempo
  (warns and keeps the cap when the word still overruns: past ~1.1x a short word stops being intelligible;
  a shouted line tolerated 1.25x). When the cap is not enough, regenerate the whole line (line_replace.py)
  instead of squeezing the word.
- level: the mean volume (volumedetect) of the source word (--match/--range) or --target-db; a limiter keeps
  peaks below -1 dBFS, so the gain is re-measured and topped up.
- writes 48 kHz stereo with 10 ms fades; prints the fitted length to put into audio.replacements.
"""

import argparse
import re
import subprocess

from common import ff


def dur(path):
    return float(subprocess.check_output([ff("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def mean_db(path, start=None, end=None):
    cmd = [ff(), "-hide_banner"]
    if start is not None:
        cmd += ["-ss", str(start), "-t", str(end - start)]
    err = subprocess.run(cmd + ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("out")
    ap.add_argument("--slot", type=float, required=True)
    ap.add_argument("--max-tempo", type=float, default=1.10)
    ap.add_argument("--target-db", type=float)
    ap.add_argument("--match")
    ap.add_argument("--range", nargs=2, type=float)
    a = ap.parse_args()
    target = a.target_db if a.target_db is not None else mean_db(a.match, *a.range)
    trim, fitted = a.out + ".trim.wav", a.out + ".fit.wav"
    subprocess.run([ff(), "-loglevel", "error", "-y", "-i", a.raw, "-af",
                    "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_threshold=-45dB:stop_duration=0.05,"
                    "aresample=48000", trim], check=True)
    d = dur(trim)
    tempo = max(1.0, d / a.slot)
    if tempo > a.max_tempo:
        print(f"WARNING needs atempo {tempo:.3f} > {a.max_tempo}: the clip overruns the slot; consider line_replace.py")
        tempo = a.max_tempo
    subprocess.run([ff(), "-loglevel", "error", "-y", "-i", trim, "-af", f"atempo={tempo:.4f}", fitted], check=True)
    fd = dur(fitted)
    gain = target - mean_db(fitted)
    for _ in range(4):
        subprocess.run([ff(), "-loglevel", "error", "-y", "-i", fitted, "-af",
                        f"volume={gain:.1f}dB,alimiter=limit=0.89:level=false,afade=t=in:d=0.01,"
                        f"afade=t=out:st={fd - 0.01:.3f}:d=0.01,aformat=channel_layouts=stereo", a.out], check=True)
        miss = target - mean_db(a.out)
        if abs(miss) < 0.5 or gain > 30:
            break
        gain += miss
    for p in (trim, fitted):
        subprocess.run(["rm", "-f", p])
    print(f"{a.out}\tlen {fd:.3f}s\tslot {a.slot}s\tatempo {tempo:.3f}\tmean {mean_db(a.out):.1f} dB (target {target:.1f})")


if __name__ == "__main__":
    main()
