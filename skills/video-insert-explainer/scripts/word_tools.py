"""Pitch shape of one key word in TTS takes, and cutting that word out of a take said inside a sentence.

usage: <asr-venv>/bin/python word_tools.py shape <out.json> --spellings 機能追加,キノーツイカ,キノウツイカ,昨日追加
                                                  --pattern LHHHHH [--isolated] <wav>...
       <asr-venv>/bin/python word_tools.py extract <outdir> --spellings ... <wav>...

shape: finds the word in the whisper transcript (any listed spelling), splits its span into len(pattern) equal
  morae, measures the median pitch per mora in semitones relative to the first, and reports
  rise   = second mora minus first (the jump that marks the accent),
  spread = range of the moras marked H (a fall inside the high part, or a re-rise read as a new phrase),
  corr   = correlation with the L/H pattern; ok = rise >= 1 and spread <= 2 semitones.
  --isolated: the whole voiced span of the take is the word (whisper cannot place a lone word).
extract: cuts the word (its first .. last character, each edge snapped to the quietest 10 ms within +-60 ms,
  never before the voice onset) to <outdir>/<basename>; check the cut by ear or by transcribing it; said inside a sentence the word keeps natural pace and shape, which a lone
  word often does not (lone words came out slow and with a fall in the wrong place).
"""

import argparse
import json
import os
import re

import numpy as np
import pyworld
import soundfile as sf

from score import asr, clamp_to_onset, level_db, load_mono


def char_times(words):
    chars = []
    for w in words:
        n = len(w["word"])
        for k, c in enumerate(w["word"]):
            chars.append((c, w["start"] + (w["end"] - w["start"]) * k / n, w["start"] + (w["end"] - w["start"]) * (k + 1) / n))
    return chars


def find(chars, spellings):
    text = "".join(c for c, _, _ in chars)
    m = re.search("|".join(map(re.escape, spellings)), text)
    return (chars[m.start()][1], chars[m.end() - 1][2]) if m else None


def shape(path, spellings, pattern, isolated):
    audio, sr = load_mono(path)
    text, words = asr(path)
    clamp_to_onset(words, audio, sr)
    span = find(char_times(words), spellings)
    if span is None and isolated:
        on = np.where(level_db(audio, sr) > -40)[0]
        span = (on[0] / 100, (on[-1] + 1) / 100) if len(on) else None
    if span is None:
        return {"file": path, "asr_text": text, "found": False, "ok": False}
    n = len(pattern)
    d = (span[1] - span[0]) / n
    f0, tt = pyworld.harvest(audio, sr, frame_period=5.0)
    st = []
    for k in range(n):
        seg = f0[(tt >= span[0] + k * d) & (tt < span[0] + (k + 1) * d) & (f0 > 0)]
        st.append(float(12 * np.log2(np.median(seg))) if len(seg) else None)
    base = next((x for x in st if x is not None), None)
    rel = [None if x is None or base is None else round(x - base, 2) for x in st]
    highs = [v for v, p in zip(rel, pattern) if p == "H" and v is not None]
    if rel[0] is None or rel[1] is None or len(highs) < 2:
        return {"file": path, "asr_text": text, "found": True, "ok": False, "st": rel, "note": "pitch not measurable"}
    rise, spread = rel[1] - rel[0], max(highs) - min(highs)
    pairs = [(1.0 if p == "H" else 0.0, v) for v, p in zip(rel, pattern) if v is not None]
    corr = float(np.corrcoef(*zip(*pairs))[0, 1]) if len({p for p, _ in pairs}) > 1 else None
    return {"file": path, "asr_text": text, "found": True, "ok": bool(rise >= 1.0 and spread <= 2.0), "rise": round(rise, 2),
            "spread": round(spread, 2), "corr": None if corr is None or not np.isfinite(corr) else round(corr, 3), "st": rel}


def quietest(lvl, t, reach=0.06):
    """The quietest 10 ms frame within +-reach of t (whisper's word edges are only roughly placed)."""
    lo, hi = max(0, int((t - reach) * 100)), min(len(lvl), int((t + reach) * 100))
    return (lo + int(np.argmin(lvl[lo:hi]))) / 100 if hi > lo else t


def extract(path, spellings, outdir):
    audio, sr = sf.read(path)
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    text, words = asr(path)
    span = find(char_times(words), spellings)
    if span is None:
        print(path, "word not found:", text)
        return
    lvl = level_db(mono.astype(np.float64), sr)
    on = np.where(lvl > -40)[0]
    onset = max(0, on[0] - 2) / 100 if len(on) else 0.0
    start, cut = max(onset, quietest(lvl, span[0])), quietest(lvl, span[1])
    out = os.path.join(outdir, os.path.basename(path))
    sf.write(out, audio[int(start * sr): int(cut * sr)].astype(np.float32), sr, subtype="PCM_16")
    print(out, f"{cut - start:.2f}s", "take:", text, "| cut heard as:", asr(out)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["shape", "extract"])
    ap.add_argument("out")
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--spellings", required=True)
    ap.add_argument("--pattern", default="")
    ap.add_argument("--isolated", action="store_true")
    a = ap.parse_args()
    spellings = a.spellings.split(",")
    if a.mode == "extract":
        os.makedirs(a.out, exist_ok=True)
        for p in a.wavs:
            extract(p, spellings, a.out)
        return
    res = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
    for p in a.wavs:
        if p not in res:
            res[p] = shape(p, spellings, a.pattern, a.isolated)
            print(json.dumps(res[p], ensure_ascii=False), flush=True)
            json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
