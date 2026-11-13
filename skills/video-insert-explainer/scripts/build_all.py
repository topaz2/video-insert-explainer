"""Render the deliverable from a finished project config (narration already built and chosen).

usage: python3 build_all.py <project.json> <out.mp4> [--skip-insert]

Steps (each prints what it did; any failure stops the run):
  1 resolve_events  events.template + timeline -> events (and its ordering checks)
  2 plates          cover plates for the source's burned-in words
  3 telops          subtitles / heading / interjection captions
  4 audio           full soundtrack, then two-pass loudnorm (target from config "master": I, TP, LRA)
  5 insert          frame-by-frame render of the insert (--skip-insert reuses <work>/insert.mp4)
  6 assemble        plates + cut + insert + mastered audio -> out.mp4 (never overwrites)
  7 checks          check_output.py (frames, sync, loudness, black/freeze) and verify_frames.py sheets
"""

import os
import subprocess
import sys

from common import Project

HERE = os.path.dirname(os.path.abspath(__file__))


def step(name, *args):
    print(f"== {name}", flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, name), *args], check=True)


def main():
    cfg, out = sys.argv[1], sys.argv[2]
    pj = Project(cfg)
    if os.path.exists(out):
        raise SystemExit(f"{out} exists; not overwriting")
    work = pj.p(pj.get("work_dir", "work"))
    os.makedirs(work, exist_ok=True)
    step("resolve_events.py", pj.p(pj.get("events_template")), pj.p(pj.get("narration.timeline")), pj.p(pj.get("events")))
    step("plates.py", cfg)
    step("make_telops.py", cfg)
    mix, final = os.path.join(work, "audio_mix.wav"), os.path.join(work, "audio_final.wav")
    step("build_audio.py", cfg, mix)
    m = pj.get("master", {})
    step("loudness.py", "normalize", mix, final, "--I", str(m.get("I", -14)), "--TP", str(m.get("TP", -1)),
         "--LRA", str(m.get("LRA", 11)), "--sr", str(pj.sr))
    insert = os.path.join(work, "insert.mp4")
    if "--skip-insert" not in sys.argv or not os.path.exists(insert):
        step("build_insert.py", cfg, "--render", insert)
    step("assemble.py", cfg, insert, final, out)
    sync = ",".join(str(t) for t in pj.get("qa.sync_times", []))
    dlg = pj.get("qa.dialogue")
    step("check_output.py", cfg, out, *(["--sync", sync] if sync else []), *(["--dialogue", f"{dlg[0]},{dlg[1]}"] if dlg else []))
    step("verify_frames.py", cfg, out, os.path.join(work, "verify"))
    print("done", out)


if __name__ == "__main__":
    main()
