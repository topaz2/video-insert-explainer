"""Quick browser preview of the insert before any rendering: the source up to the cut, the slides with narration,
subtitles, interjections and page turns, a white flash, then the source again.

usage: python3 preview.py <project.json> [--pre 10] [--post 15]  -> <work>/preview/index.html

Encodes a VP9/Opus clip of the source around the cut (headless Chromium builds often lack H.264) and writes a
page driven by the resolved events, timeline.json and the subtitles - the same numbers the real render uses.
It is a sketch for timing and wording review (no zooms, markers or plates); the render is the deliverable.
"""

import argparse
import json
import os

from common import Project, ff, run

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Insert preview</title><style>
:root{--bg:#111;--fg:#fff}body{margin:0;background:var(--bg);color:var(--fg);font-family:"Hiragino Sans",system-ui,sans-serif}
#wrap{display:flex;flex-direction:column;align-items:center;gap:10px;padding:12px 16px}
#stage{position:relative;width:min(100%,1280px);aspect-ratio:16/9;background:#000;overflow:hidden}
#stage video,#stage img.slide{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
#stage img.slide{background:#fff;display:none}#stage img.small{transform:scale(.55);box-shadow:0 12px 24px rgba(0,0,0,.5)}
#sub{position:absolute;bottom:3.7%;left:0;right:0;margin:0 auto;width:fit-content;max-width:96%;text-align:center;font-weight:600;
font-size:clamp(12px,2.3vw,29px);background:rgba(0,0,0,.6);border-radius:10px;padding:.35em .6em;display:none}
#head{position:absolute;top:5.5%;left:0;right:0;text-align:center;font-weight:800;font-size:clamp(16px,3.3vw,42px);
-webkit-text-stroke:2px #000;paint-order:stroke fill;display:none}#pip{position:absolute;width:20%;display:none;border:3px solid #fff}
#flash{position:absolute;inset:0;background:#fff;opacity:0;transition:opacity .08s;pointer-events:none}
button{font-size:18px;padding:.5em 1.6em;border-radius:8px;border:0;background:#1971C2;color:#fff}
</style></head><body><div id="wrap"><div id="stage"><video id="v" src="clip.webm" preload="auto" playsinline></video>
__SLIDES__<img id="pip" alt=""><div id="head"></div><div id="sub"></div><div id="flash"></div></div>
<button id="go">Play</button><div id="st"></div></div><audio id="narr" src="__NARR__" preload="auto"></audio>__AUDIO__
<script>
const D=__DATA__,$=id=>document.getElementById(id),v=$("v"),sl=[...document.querySelectorAll(".slide")];
let ph="idle",t0=0,fired=new Set();const once=(k,f)=>{if(!fired.has(k)){fired.add(k);f()}};
function show(i,small){sl.forEach((s,k)=>{s.style.display=k===i?"block":"none";s.classList.toggle("small",!!small)})}
function tick(t){const pg=D.pages.find(p=>t>=p[1]&&t<p[2]);
 if(t<D.expand)show(0,true);else if(t<D.shrink)show(pg?pg[0]-1:D.last-1,false);else if(t<D.exit)show(D.last-1,true);else show(-1);
 $("head").style.display=D.head&&t>=D.head.start&&t<D.head.end?"block":"none";
 const s=D.subs.find(x=>t>=x.s&&t<x.e);$("sub").style.display=s?"block":"none";if(s)$("sub").innerHTML=s.t;
 let pip=null;D.ij.forEach((j,i)=>{if(t>=j.t)once("ij"+i,()=>{const a=$("ij"+i);if(a)a.play()});if(t>=j.t-0.1&&t<j.t+0.8)pip=j});
 $("pip").style.display=pip?"block":"none";if(pip){$("pip").src=pip.pip;$("pip").style.left=pip.x+"%";$("pip").style.top=pip.y+"%"}
 D.sfx.forEach((f,i)=>f.times.forEach((x,k)=>{if(t>=x)once("fx"+i+"_"+k,()=>{const a=$("fx"+i).cloneNode();a.play()})}));
 if(t>=D.len-0.16)once("end",()=>{$("flash").style.opacity=1;setTimeout(()=>{show(-1);$("sub").style.display="none";
 $("pip").style.display="none";v.currentTime=D.cut;v.play();$("flash").style.opacity=0;ph="post"},90)})}
function loop(){if(ph==="pre"&&v.currentTime>=D.cut-0.05){ph="ins";v.pause();$("narr").currentTime=0;$("narr").play();t0=performance.now()}
 else if(ph==="ins")tick((performance.now()-t0)/1000);if(ph!=="done")requestAnimationFrame(loop)}
$("go").onclick=async()=>{fired=new Set();v.currentTime=0;await v.play();ph="pre";requestAnimationFrame(loop)};
v.addEventListener("ended",()=>{ph="done"});
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--pre", type=float, default=10)
    ap.add_argument("--post", type=float, default=15)
    a = ap.parse_args()
    pj = Project(a.project)
    ev = pj.events
    out = pj.p(pj.get("work_dir", "work") + "/preview")
    os.makedirs(out, exist_ok=True)
    cut = pj.cut_frame / pj.fps
    start = max(0.0, cut - a.pre)
    run([ff(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{a.pre + a.post:.3f}", "-i", pj.base,
         "-vf", "scale=1280:-2", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "2500k",
         "-c:a", "libopus", os.path.join(out, "clip.webm")])
    rel = lambda p: os.path.relpath(pj.p(p), out)  # noqa: E731
    tl = json.load(open(pj.p(pj.get("narration.timeline")), encoding="utf-8"))
    subs_txt = json.load(open(pj.p(pj.get("narration.subtitles")), encoding="utf-8"))
    subs = [{"s": s.get("voice", s["start"]), "e": s["end"], "t": subs_txt.get(s["id"], "").replace("／", "<br>")} for s in tl["segs"]]
    subs += [{"s": j["t"], "e": j["t"] + j["dur"], "t": j["text"]} for j in ev.get("interjections", [])]
    px, py = ev.get("pip_pos", [1500, 620])
    data = {"cut": cut - start, "pages": ev["pages"], "last": ev["pages"][-1][0], "expand": ev["entry"]["expand"][1],
            "shrink": ev["shrink"][0], "exit": ev["exit"][1], "len": ev["insert_len"], "head": ev.get("heading"),
            "subs": sorted(subs, key=lambda x: x["s"]), "sfx": [{"times": f["times"]} for f in ev.get("sfx", [])],
            "ij": [{"t": j["t"], "pip": rel(j["pip"]), "x": px / 19.2, "y": py / 10.8} for j in ev.get("interjections", [])]}
    slides = "".join(f'<img class="slide" src="{rel(p)}" alt="">' for p in pj.get("slides"))
    audio = "".join(f'<audio id="fx{i}" src="{rel(f["file"])}" preload="auto"></audio>' for i, f in enumerate(ev.get("sfx", [])))
    audio += "".join(f'<audio id="ij{i}" src="{rel(j["sound"])}" preload="auto"></audio>' for i, j in enumerate(ev.get("interjections", [])) if j.get("sound"))
    page = PAGE.replace("__SLIDES__", slides).replace("__AUDIO__", audio).replace("__NARR__", rel(pj.get("narration.full")))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page.replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    print("wrote", os.path.join(out, "index.html"))


if __name__ == "__main__":
    main()
