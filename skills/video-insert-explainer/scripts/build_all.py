"""Render the deliverable from a project config, each stage starting as soon as its inputs exist.

usage: python3 build_all.py <project.json> <out.mp4> [--narrate] [--tts-workers N] [--skip-insert] [--sequential]

Stages (<- the stages each one waits for):
  narrate   build_narration.py --engine clone (TTS workers on the GPU; only with --narrate - without it the
            chosen narration, timeline.json and narration_full.wav, must already exist)
  plates    plates.py                                                    (config only: runs alongside the TTS)
  resolve   resolve_events.py: events.template + timeline -> events      <- narrate
  telops    make_telops.py                                               <- resolve
  mix       build_audio.py: full soundtrack                              <- resolve
  master    loudness.py normalize, two-pass (config "master": I, TP, LRA) <- mix
  insert    build_insert.py --render                                     <- telops
            (--skip-insert reuses <work>/insert.mp4 when it exists)
  assemble  assemble.py -> out.mp4 (never overwrites)                    <- plates, insert, master
  check     check_output.py (frames, sync, loudness, black/freeze)       <- assemble
  verify    verify_frames.py sheets from config "checks"                 <- assemble
So the insert render overlaps the soundtrack and loudnorm, and the two QA stages run together. Nothing here
shares the GPU with the TTS; run score.py (whisper) only after the narration is generated.
Measured (8.8 min source, 31 s insert): 213 s one by one, 196 s as a graph. assemble's full re-encode (x264 slow,
already multithreaded) takes 146 s of it and has nothing to run beside it.
Each stage writes <work>/logs/<stage>.log and the run ends with a wall-clock table. A failing stage stops the
run: stages still running are terminated, the failing log's tail is printed, and the exit status is 1.
--sequential runs the same stages one at a time (comparison, or a machine short of memory).
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from common import Project

HERE = os.path.dirname(os.path.abspath(__file__))


def stages_for(pj, cfg, out, a):
    py, work = sys.executable, pj.p(pj.get("work_dir", "work"))
    s = lambda name: os.path.join(HERE, name)  # noqa: E731
    mix, final, insert = (os.path.join(work, n) for n in ("audio_mix.wav", "audio_final.wav", "insert.mp4"))
    m = pj.get("master", {})
    sync = ",".join(str(t) for t in pj.get("qa.sync_times", []))
    dlg = pj.get("qa.dialogue")
    st = []
    if a.narrate:
        st.append(("narrate", [], [py, s("build_narration.py"), cfg, "--engine", "clone",
                                   *(["--workers", str(a.tts_workers)] if a.tts_workers else [])]))
    st += [
        ("plates", [], [py, s("plates.py"), cfg]),
        ("resolve", ["narrate"] if a.narrate else [],
         [py, s("resolve_events.py"), pj.p(pj.get("events_template")), pj.p(pj.get("narration.timeline")), pj.p(pj.get("events"))]),
        ("telops", ["resolve"], [py, s("make_telops.py"), cfg]),
        ("mix", ["resolve"], [py, s("build_audio.py"), cfg, mix]),
        ("master", ["mix"], [py, s("loudness.py"), "normalize", mix, final, "--I", str(m.get("I", -14)),
                             "--TP", str(m.get("TP", -1)), "--LRA", str(m.get("LRA", 11)), "--sr", str(pj.sr)]),
    ]
    reuse = a.skip_insert and os.path.exists(insert)
    if not reuse:
        st.append(("insert", ["telops"], [py, s("build_insert.py"), cfg, "--render", insert]))
    st += [
        ("assemble", ["plates", "master"] + ([] if reuse else ["insert"]), [py, s("assemble.py"), cfg, insert, final, out]),
        ("check", ["assemble"], [py, s("check_output.py"), cfg, out, *(["--sync", sync] if sync else []),
                                 *(["--dialogue", f"{dlg[0]},{dlg[1]}"] if dlg else [])]),
        ("verify", ["assemble"], [py, s("verify_frames.py"), cfg, out, os.path.join(work, "verify")]),
    ]
    return st


def stop(running):
    for p, _, log in running.values():
        try:
            os.killpg(p.pid, signal.SIGTERM)  # the insert stage has chunk renders of its own
        except ProcessLookupError:
            pass
        p.wait()
        log.close()


def run_graph(stages, logs, sequential):
    t_start, pending, running, done = time.time(), list(stages), {}, {}
    clock = lambda: time.time() - t_start  # noqa: E731
    while pending or running:
        for st in list(pending):
            name, deps, cmd = st
            if all(d in done for d in deps) and not (sequential and running):
                log = open(os.path.join(logs, name + ".log"), "w")
                running[name] = (subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True), clock(), log)
                pending.remove(st)
                print(f"[{clock():7.1f}s] start {name}", flush=True)
        for name, (p, t0, log) in list(running.items()):
            rc = p.poll()
            if rc is None:
                continue
            log.close()
            del running[name]
            if rc:
                stop(running)
                path = os.path.join(logs, name + ".log")
                print(f"[{clock():7.1f}s] FAILED {name} (exit {rc}); last lines of {path}:", flush=True)
                print("".join(open(path, encoding="utf-8", errors="replace").readlines()[-20:]), flush=True)
                return 1
            done[name] = (t0, clock())
            print(f"[{clock():7.1f}s] done  {name} ({done[name][1] - t0:.1f}s)", flush=True)
        time.sleep(0.2)
    print(f"{'stage':10} {'start':>8} {'end':>8} {'took':>8}")
    for name, (t0, t1) in done.items():
        print(f"{name:10} {t0:8.1f} {t1:8.1f} {t1 - t0:8.1f}")
    print(f"{'total':10} {'':8} {clock():8.1f}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("out")
    ap.add_argument("--narrate", action="store_true")
    ap.add_argument("--tts-workers", type=int, default=0)
    ap.add_argument("--skip-insert", action="store_true")
    ap.add_argument("--sequential", action="store_true")
    a = ap.parse_args()
    pj = Project(a.project)
    if os.path.exists(a.out):
        raise SystemExit(f"{a.out} exists; not overwriting")
    work = pj.p(pj.get("work_dir", "work"))
    logs = os.path.join(work, "logs")
    os.makedirs(logs, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rc = run_graph(stages_for(pj, pj.path, os.path.abspath(a.out), a), logs, a.sequential)
    if rc == 0:
        print("done", a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
