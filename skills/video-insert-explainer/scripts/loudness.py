"""Loudness: measure (EBU R128 integrated / true peak) or two-pass loudnorm with a linear-mode guard.

usage: python3 loudness.py measure <file> [--start S --dur D]
       python3 loudness.py normalize <in.wav> <out.wav> [--I -14 --TP -1 --LRA 11 --sr 48000]

normalize exits 4 when loudnorm falls back to dynamic mode (it then pumps the level, which audibly
changes the source dialogue). Linear mode needs input LRA <= --LRA and input TP + (I - input I) <= --TP:
bring the mix close to the target with the mix gains first (audio.narration_gain_db / extra_db), so loudnorm
only trims.
"""

import argparse
import json
import re
import subprocess

from common import ff


def measure(path, start=None, dur=None):
    cmd = [ff(), "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    tail = err[err.rfind("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+) LUFS", tail).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", tail).group(1))
    return {"I": i, "TP": tp}


def normalize(src, dst, I, TP, LRA, sr):
    target = f"loudnorm=I={I}:TP={TP}:LRA={LRA}"
    err = subprocess.run([ff(), "-hide_banner", "-nostats", "-i", src, "-af", target + ":print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = json.loads(err[err.rfind("{"): err.rfind("}") + 1])
    args = (f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true:print_format=json")
    err2 = subprocess.run([ff(), "-hide_banner", "-nostats", "-y", "-i", src, "-af", f"{target}:{args}", "-ar", str(sr),
                           "-c:a", "pcm_s24le", dst], capture_output=True, text=True).stderr
    if '"normalization_type" : "linear"' not in err2:
        print("loudnorm fell back to dynamic mode")
        raise SystemExit(4)
    print(json.dumps({"pass1": {"I": m["input_i"], "TP": m["input_tp"]}, "out": measure(dst)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["measure", "normalize"])
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--start", type=float)
    ap.add_argument("--dur", type=float)
    ap.add_argument("--I", type=float, default=-14)
    ap.add_argument("--TP", type=float, default=-1)
    ap.add_argument("--LRA", type=float, default=11)
    ap.add_argument("--sr", type=int, default=48000)
    a = ap.parse_args()
    if a.mode == "measure":
        print(json.dumps(measure(a.src, a.start, a.dur)))
    else:
        normalize(a.src, a.dst, a.I, a.TP, a.LRA, a.sr)


if __name__ == "__main__":
    main()
