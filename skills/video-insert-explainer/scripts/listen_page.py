"""Listening page for picking TTS takes: one section per sentence, takes sorted by score, a radio per take.

usage: python3 listen_page.py <out.html> <scores.json> [<scores2.json> ...] [--texts texts.json]

Every take in the score files (score.py output) gets a player, its total / asr / accent / flow, the whisper
transcript and the accent phrases whose correlation is below 0.3 (the likely mis-accented words).
Picking radios fills a JSON box ({"<id>": "<absolute wav path>"}) the user copies back; it goes into
narration.take as is.
Audio paths are written relative to the page, so open the page from the same disk (no server needed).
"""

import argparse
import html
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("scores", nargs="+")
    ap.add_argument("--texts")
    a = ap.parse_args()
    takes = {}
    for path in a.scores:
        takes.update(json.load(open(path, encoding="utf-8")))
    texts = {o["id"]: o["reading"] for o in json.load(open(a.texts, encoding="utf-8"))} if a.texts else {}
    by_id = {}
    for f, r in takes.items():
        by_id.setdefault(r.get("id", "?"), []).append((f, r))
    base = os.path.dirname(os.path.abspath(a.out))
    parts = []
    for sid in sorted(by_id):
        rows = sorted(by_id[sid], key=lambda x: -x[1].get("total", 0))
        parts.append(f'<section><h2>{html.escape(sid)}</h2><p class="ref">{html.escape(texts.get(sid, ""))}</p><table>')
        for i, (f, r) in enumerate(rows):
            rel = os.path.relpath(os.path.abspath(f), base)
            weak = [p["kana"] for p in r.get("phrases", []) if p.get("corr") is not None and p["corr"] < 0.3]
            note = "・".join(r.get("flow_notes", []) + ([f"accent? {'、'.join(weak)}"] if weak else []))
            parts.append(
                f'<tr><td><input type="radio" name="{html.escape(sid)}" value="{html.escape(os.path.abspath(f))}"{" checked" if i == 0 else ""}></td>'
                f'<td><audio controls preload="none" src="{html.escape(rel)}"></audio></td>'
                f'<td class="n">{r.get("total", 0)}</td><td class="n">{r.get("asr", "")}/{r.get("accent", "")}/{r.get("flow", "")}</td>'
                f'<td>{html.escape(r.get("asr_text", r.get("error", "")))}<div class="note">{html.escape(note)}</div>'
                f'<div class="file">{html.escape(os.path.basename(f))}</div></td></tr>')
        parts.append("</table></section>")
    page = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice take picker</title><style>
:root{{--bg:#fff;--fg:#1a1a1a;--muted:#666;--line:#ddd;--warn:#b45309}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8e8e8;--muted:#9aa;--line:#333;--warn:#f59e0b}}}}
body{{background:var(--bg);color:var(--fg);font-family:system-ui,"Hiragino Sans",sans-serif;margin:0 auto;max-width:1100px;padding:16px}}
table{{border-collapse:collapse;width:100%}}td{{border-top:1px solid var(--line);padding:6px;vertical-align:top}}
.n{{font-variant-numeric:tabular-nums;white-space:nowrap}}.ref,.file{{color:var(--muted)}}.note{{color:var(--warn);font-size:.9em}}
.file{{font-size:.8em}}audio{{width:260px;max-width:60vw}}#pick{{position:sticky;bottom:0;width:100%;height:6em;background:var(--bg);color:var(--fg)}}
</style></head><body><h1>Voice take picker</h1><p>Sorted by score (total; asr/accent/flow). Listen, pick one per sentence, copy the JSON.</p>
{''.join(parts)}<textarea id="pick" readonly></textarea><script>
function upd(){{const o={{}};document.querySelectorAll('input[type=radio]:checked').forEach(r=>o[r.name]=r.value);
document.getElementById('pick').value=JSON.stringify(o,null,1)}}
document.querySelectorAll('input[type=radio]').forEach(r=>r.addEventListener('change',upd));upd();
</script></body></html>"""
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    print("wrote", a.out, sum(len(v) for v in by_id.values()), "takes in", len(by_id), "sentences")


if __name__ == "__main__":
    main()
