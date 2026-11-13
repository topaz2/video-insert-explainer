"""Final assembly: plates on the source timeline, cut at cut_frame, the rendered insert in between, the mastered
soundtrack; H.264 crf 18 / AAC stereo.

usage: python3 assemble.py <project.json> <insert.mp4> <audio.wav> <out.mp4> [--preset medium|slow|...]

x264 preset: --preset, else config "master.preset", else medium (measured on an 8.8 min 1080p30 source: 103 s
against 140 s for slow, at the same crf 18).

Plates go on BEFORE the cut, on the source timeline, so their measured times stay valid after the insert.
The white flash rises at the end of the insert (build_insert.py) and falls on the first source frames here.
"""

import argparse
import json
import os
import subprocess
import sys

from common import FLASH_HALF, Project, ff
from filter_template import build


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("insert")
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--preset", default="")
    a = ap.parse_args()
    pj = Project(a.project)
    insert, audio, out = a.insert, a.audio, a.out
    preset = a.preset or pj.get("master.preset", "medium")
    if os.path.exists(out):
        raise SystemExit(f"{out} exists; not overwriting")
    work = pj.p(pj.get("work_dir", "work"))
    manifest = os.path.join(work, "plates", "manifest.json")
    rows = json.load(open(manifest, encoding="utf-8")) if os.path.exists(manifest) else []
    plate_inputs, chain = build(rows, fps=pj.fps)
    i_ins, i_aud = len(rows) + 1, len(rows) + 2
    cut = pj.cut_frame
    chain = chain.replace("[vout]", "[plated]")
    chain += (";\n[plated]split=2[pa][pc]"
              f";\n[pa]trim=start_frame=0:end_frame={cut},setpts=PTS-STARTPTS,setsar=1[a]"
              f";\n[pc]trim=start_frame={cut},setpts=PTS-STARTPTS,setsar=1,fade=t=in:st=0:d={FLASH_HALF}:color=white[c]"
              f";\n[{i_ins}:v]setpts=PTS-STARTPTS,format=yuv420p,setsar=1[i]"
              ";\n[a][i][c]concat=n=3:v=1:a=0[v]")
    script = os.path.join(work, "assemble_filter.txt")
    with open(script, "w") as f:
        f.write(chain + "\n")
    cmd = [ff(), "-hide_banner", "-y", "-i", pj.base, *plate_inputs, "-i", insert, "-i", audio,
           "-filter_complex_script", script, "-map", "[v]", "-map", f"{i_aud}:a",
           "-c:v", "libx264", "-crf", "18", "-preset", preset, "-pix_fmt", "yuv420p", "-r", str(pj.fps),
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "192k", "-ar", str(pj.sr), "-ac", "2", "-movflags", "+faststart", out]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
