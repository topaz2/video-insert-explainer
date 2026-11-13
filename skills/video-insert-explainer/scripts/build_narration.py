"""Synthesize the narration clips, lay them out on the insert timeline and mix narration_full.wav.

usage: python3 build_narration.py <project.json> [--engine clone|say] [--only id,id] [--workers N]

Config "narration":
  sentences   JSON list [{"id": "n1_00", "page": 1, "say": "<reading text>", "seed": 11}]  (the text the TTS
              reads; katakana / kana spellings that fix the accent go here, the subtitles stay separate)
  clips_dir, timeline, full     output paths
  start (2.6), gap (0.10), page_breath (0.8), page_breath_overrides {"<page>": seconds}, end_pad (0.5)
  take        optional {"<id>": "<wav>"} to use a chosen candidate (listening page) instead of synthesizing
Engine "clone" runs scripts/clone_say.py with tts.python (needs rights.voice_clone_authorized) in --workers
processes (default tts.workers, 2) started tts.stagger seconds apart (default 25; each model load peaks at ~4.2 GB);
they share the job list, each taking the next unclaimed sentence. A later worker starts only while at least
tts.min_left (default 6) sentences are unclaimed: 7 sentences took 39 s with 1 worker and 44 s with 2.
Measured on one Apple-silicon machine: 7.9 takes/min with 1 worker, 11.0 with 2, 10.5 with 4. "say" is the
macOS voice (tts.say_voice, default Kyoko), for timing drafts only - never in a deliverable.
Clone clips end with 0.25 s of silence, which is why the default gap is 0.10 s (0.35 s heard).
timeline.json segs carry start, end and "voice" = start + measured voice onset (first 10 ms window above -35 dB:
-45 dB catches head noise of some takes; at -35 dB the others move by 0.04 s at most).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import soundfile as sf

from common import Project, ff

ONSET_DB = -35.0
HERE = os.path.dirname(os.path.abspath(__file__))


def duration(path):
    return float(subprocess.check_output([ff("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


def onset(path):
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    w = sr // 100
    n = len(y) // w
    db = 20 * np.log10(np.sqrt((y[: n * w].reshape(n, w) ** 2).mean(axis=1)) + 1e-12)
    loud = np.nonzero(db > ONSET_DB)[0]
    return float(loud[0] * w / sr) if len(loud) else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--engine", default="clone", choices=["clone", "say"])
    ap.add_argument("--only", default="")
    ap.add_argument("--workers", type=int, default=0)
    a = ap.parse_args()
    pj = Project(a.project)
    nc = pj.get("narration")
    sents = json.load(open(pj.p(nc["sentences"]), encoding="utf-8"))
    clips = pj.p(nc.get("clips_dir", "work/narration/clips"))
    os.makedirs(clips, exist_ok=True)
    only = set(filter(None, a.only.split(",")))
    take = nc.get("take", {})
    ext = ".aiff" if a.engine == "say" else ".wav"
    for s in sents:
        s["file"] = os.path.join(clips, s["id"] + ext)
    todo = [s for s in sents if (not only or s["id"] in only) and s["id"] not in take]
    for s in todo:
        if os.path.exists(s["file"]):
            os.unlink(s["file"])
    if a.engine == "say":
        for s in todo:
            subprocess.run(["say", "-v", pj.get("tts.say_voice", "Kyoko"), "-r", str(pj.get("tts.say_rate", 200)), "-o", s["file"], s["say"]], check=True)
    elif todo:
        jobs = os.path.join(clips, "_jobs.json")
        json.dump([{"text": s["say"], "out": s["file"], "seed": s.get("seed", 1234)} for s in todo], open(jobs, "w"), ensure_ascii=False)
        n = max(1, min(a.workers or pj.get("tts.workers", 2), len(todo)))
        cmd = [pj.p(pj.get("tts.python")), os.path.join(HERE, "clone_say.py"), "--project", pj.path, "--jobs", jobs]
        procs = []
        for k in range(n):
            if k:
                time.sleep(pj.get("tts.stagger", 25))
                left = sum(not (os.path.exists(s["file"]) or os.path.exists(s["file"] + ".claim")) for s in todo)
                if left < pj.get("tts.min_left", 6):
                    break  # another model load would not pay for itself
            procs.append(subprocess.Popen(cmd))
        if any(p.wait() for p in procs):
            raise SystemExit("clone_say.py failed")
    for s in sents:  # clips kept from an earlier run may come from the other engine (.aiff draft vs .wav clone)
        if s not in todo and s["id"] not in take and not os.path.exists(s["file"]):
            alt = os.path.splitext(s["file"])[0] + (".wav" if ext == ".aiff" else ".aiff")
            if not os.path.exists(alt):
                raise SystemExit(f'{s["id"]}: no clip; run without --only first')
            s["file"] = alt
    for sid, wav in take.items():
        s = next(x for x in sents if x["id"] == sid)
        s["file"] = os.path.join(clips, sid + ".wav")
        shutil.copyfile(pj.p(wav), s["file"])

    t, prev, segs = nc.get("start", 2.6), None, []
    over = nc.get("page_breath_overrides", {})
    for s in sents:
        if prev is not None and s["page"] != prev:
            t += over.get(str(s["page"]), nc.get("page_breath", 0.8))
        d = duration(s["file"])
        seg = {"id": s["id"], "page": s["page"], "file": s["file"], "say": s["say"], "dur": round(d, 3),
               "start": round(t, 3), "end": round(t + d, 3)}
        seg["voice"] = round(seg["start"] + onset(s["file"]), 3)
        segs.append(seg)
        t, prev = seg["end"] + nc.get("gap", 0.10), s["page"]
    end = round(t + nc.get("end_pad", 0.5), 3)
    json.dump({"engine": a.engine, "segs": segs, "narr_end": end}, open(pj.p(nc["timeline"]), "w"), ensure_ascii=False, indent=1)
    inp, flt = [], []
    for k, s in enumerate(segs):
        ms = round(s["start"] * 1000)
        inp += ["-i", s["file"]]
        flt.append(f"[{k}]aresample={pj.sr},aformat=channel_layouts=stereo,adelay={ms}|{ms}[a{k}]")
    flt.append("".join(f"[a{k}]" for k in range(len(segs))) + f"amix=inputs={len(segs)}:normalize=0,apad=whole_dur={end}[out]")
    subprocess.run([ff(), "-loglevel", "error", "-y", *inp, "-filter_complex", ";".join(flt), "-map", "[out]", "-t", str(end),
                    "-c:a", "pcm_s16le", pj.p(nc["full"])], check=True)
    for s in segs:
        print(f'{s["id"]} {s["start"]:7.2f}-{s["end"]:7.2f} voice {s["voice"]:7.2f}  {s["say"]}')
    print("narration end", end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
