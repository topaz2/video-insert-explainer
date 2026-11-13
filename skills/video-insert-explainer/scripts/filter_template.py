"""Turn a plates manifest into ffmpeg inputs + a filter_complex script that overlays each PNG only in its window.

usage: python3 filter_template.py <manifest.json> <out_script.txt> [--offset SEC] [--only ID,ID,...] [--fps 30]
  prints the "-i ..." arguments for the PNG inputs (input 0 is the base video, PNGs start at 1).
  --offset: subtract from every window when the base input is cut with -ss (timestamps then start at 0).
"""

import argparse
import json
import shlex


def build(rows, offset=0.0, fps=30):
    """Rows with fade_in/fade_out > 0 become a looped stream faded on alpha; the rest are single stills."""
    inputs, chains, label = [], [], "0:v"
    for i, r in enumerate(rows, start=1):
        s, e = r["start"] - offset, r["end"] - offset
        fi, fo = r.get("fade_in", 0), r.get("fade_out", 0)
        src = f"{i}:v"
        if fi or fo:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{e:.4f}", "-i", r["png"]]
            fades = ["format=rgba"]
            if fi:
                fades.append(f"fade=t=in:st={s:.4f}:d={fi}:alpha=1")
            if fo:
                fades.append(f"fade=t=out:st={e - fo:.4f}:d={fo}:alpha=1")
            chains.append(f"[{src}]{','.join(fades)}[f{i}]")
            src = f"f{i}"
        else:
            inputs += ["-i", r["png"]]
        eof = "pass" if fi or fo else "repeat"
        chains.append(f"[{label}][{src}]overlay=0:0:eof_action={eof}:enable='gte(t,{s:.4f})*lt(t,{e:.4f})'[v{i}]")
        label = f"v{i}"
    chains.append(f"[{label}]null[vout]")
    return inputs, ";\n".join(chains)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("script")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--fps", type=int, default=30)
    a = ap.parse_args()
    rows = json.load(open(a.manifest, encoding="utf-8"))
    if a.only:
        keep = tuple(a.only.split(","))
        rows = [r for r in rows if r["id"].startswith(keep)]
    inputs, script = build(rows, a.offset, a.fps)
    with open(a.script, "w") as f:
        f.write(script + "\n")
    print(" ".join(shlex.quote(x) for x in inputs))


if __name__ == "__main__":
    main()
