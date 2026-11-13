"""Score TTS takes of a sentence for reading, pitch accent and flow, to rank candidates before the user listens.

usage: <asr-venv>/bin/python score.py <out.json> --texts texts.json [--fix fix.json] <wav>...
  texts.json  [{"id": "n1_00", "reading": "<sentence as it should be heard>"}]; a wav belongs to the id its
              basename starts with (longest match), e.g. n1_00_K_s22.wav -> n1_00
  fix.json    [["<whisper spelling>", "<reading>"], ...] for spellings whose pyopenjtalk reading differs from
              what was said (digits, Latin brand words, homophone kanji) - project data, not code
Needs mlx-whisper (Apple Silicon), pyopenjtalk(-plus), pyworld, soundfile. Results are cached in out.json.

Per take (0..1 each; total 0..100 = 40 asr + 40 accent + 20 flow):
  asr     1 - kana error rate of the whisper transcript against the reading
  accent  per accent phrase, correlation of the voice pitch per mora with the Tokyo pitch-accent pattern from
          pyopenjtalk (type 0: L H H..., type 1: H L L..., type n: L H..H(n) L...); "phrases" lists each
          phrase's kana, expected highs and semitones, so a single mis-accented word is visible
  flow    penalties for an inner pause > 0.55 s, a rate outside 5.5-10 mora/s, an unheard ending, a stretched mora
The score only orders candidates; the user's ears pick (listen_page.py).
"""

import argparse
import difflib
import json
import os
import re

import mlx_whisper
import numpy as np
import pyopenjtalk
import pyworld
import soundfile as sf

SMALL = set("ァィゥェォャュョヮ")
ASR_MODEL = os.environ.get("ASR_MODEL", "mlx-community/whisper-large-v3-turbo")


def morae(kana):
    out = []
    for ch in kana:
        if ch in SMALL and out:
            out[-1] += ch
        elif re.match(r"[ァ-ヴー]", ch):
            out.append(ch)
    return out


def kana_of(text):
    return pyopenjtalk.g2p(text, kana=True)


def target_accent(text):
    """[{phrase, pos, high}] per mora; a phrase starts when the mora position resets or after a pause."""
    groups, prev_pos, phrase = [], None, -1
    for lab in pyopenjtalk.extract_fullcontext(text):
        ph = re.search(r"\-(.+?)\+", lab).group(1)
        if ph in ("sil", "pau"):
            prev_pos = None
            continue
        a = re.search(r"/A:(-?\d+|xx)\+(\d+|xx)\+(\d+|xx)/", lab)
        f = re.search(r"/F:(\d+|xx)_(\d+|xx)#", lab)
        if not a or a.group(2) == "xx":
            continue
        pos = int(a.group(2))
        if pos == prev_pos:
            continue
        if prev_pos is None or pos < prev_pos:
            phrase += 1
        acc = int(f.group(2)) if f and f.group(2) != "xx" else 0
        high = (pos == 1) if acc == 1 else (pos >= 2 and (acc == 0 or pos <= acc))
        groups.append({"phrase": phrase, "pos": pos, "high": int(high)})
        prev_pos = pos
    return groups


def asr(path):
    r = mlx_whisper.transcribe(path, path_or_hf_repo=ASR_MODEL, language="ja", word_timestamps=True,
                               condition_on_previous_text=False, temperature=0)
    return r["text"], [w for s in r["segments"] for w in s.get("words", [])]


def load_mono(path):
    audio, sr = sf.read(path)
    audio = audio.astype(np.float64)
    return (audio.mean(axis=1) if audio.ndim > 1 else audio), sr


def level_db(audio, sr):
    w = int(sr * 0.01)
    n = len(audio) // w
    return 20 * np.log10(np.sqrt((audio[: n * w].reshape(n, w) ** 2).mean(axis=1)) + 1e-9)


def clamp_to_onset(words, audio, sr):
    """whisper often starts the first word at 0.0 although the voice starts later."""
    on = np.where(level_db(audio, sr) > -40)[0]
    onset = on[0] / 100 if len(on) else 0.0
    for w in words:
        if w["start"] < onset:
            w["start"] = min(onset, w["end"] - 0.02)


def mora_times(words):
    out = []
    for w in words:
        ms = morae(kana_of(w["word"]))
        d = (w["end"] - w["start"]) / max(1, len(ms))
        out += [(m, w["start"] + k * d, w["start"] + (k + 1) * d) for k, m in enumerate(ms)]
    return out


def score(path, reading, fixes):
    ref_m = morae(kana_of(reading))
    audio, sr = load_mono(path)
    text, words = asr(path)
    clamp_to_onset(words, audio, sr)
    hyp = mora_times(words)
    sm = difflib.SequenceMatcher(a=ref_m, b=[m for m, _, _ in hyp], autojunk=False)
    full = text
    for x, y in fixes:
        full = full.replace(x, y)
    full_m = morae(kana_of(full))
    matched = sum(b.size for b in difflib.SequenceMatcher(a=ref_m, b=full_m, autojunk=False).get_matching_blocks())
    asr_s = max(0.0, matched / max(1, len(ref_m)) - 0.5 * max(0, len(full_m) - len(ref_m)) / max(1, len(ref_m)))

    t = [None] * len(ref_m)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            t[blk.a + k] = hyp[blk.b + k][1:]
    known = [k for k, x in enumerate(t) if x]
    for k in range(len(t)):  # unmatched morae: spread evenly between matched neighbours
        if t[k] is None and known:
            lo = max([j for j in known if j < k], default=None)
            hi = min([j for j in known if j > k], default=None)
            if lo is not None and hi is not None:
                d = (t[hi][0] - t[lo][1]) / max(hi - lo - 1, 1)
                i = k - lo - 1
                t[k] = (t[lo][1] + i * d, t[lo][1] + (i + 1) * d)

    f0, tt = pyworld.harvest(audio, sr, frame_period=5.0)
    lf0 = np.where(f0 > 0, np.log(np.maximum(f0, 1)), np.nan)
    acc = target_accent(reading)
    corrs, rows = [], []
    if len(acc) == len(ref_m) and known:
        pitch = np.array([np.nanmedian(seg) if x and np.isfinite(seg := lf0[(tt >= x[0]) & (tt < x[1])]).any() else np.nan for x in t])
        phrases = {}
        for k, g in enumerate(acc):
            phrases.setdefault(g["phrase"], []).append(k)
        for ks in phrases.values():
            exp = np.array([acc[k]["high"] for k in ks], float)
            obs = pitch[ks]
            ok = np.isfinite(obs)
            c = None
            if ok.sum() >= 3 and exp[ok].min() != exp[ok].max():
                c = np.corrcoef(exp[ok], obs[ok])[0, 1]
                c = float(c) if np.isfinite(c) else None
                if c is not None:
                    corrs.append(c)
            base = obs[ok][0] if ok.any() else np.nan
            rows.append({"kana": "".join(ref_m[k] for k in ks), "exp": [int(x) for x in exp], "corr": None if c is None else round(c, 3),
                         "st": [None if not np.isfinite(v) else round(float(12 * (v - base) / np.log(2)), 2) for v in obs]})
    accent_s = (float(np.mean(corrs)) + 1) / 2 if corrs else 0.5

    db = level_db(audio, sr)
    voiced = np.where(db > -40)[0]
    pen, notes = 0.0, []
    if len(voiced):
        long_gaps = [g / 100 for g in np.diff(voiced) if g / 100 > 0.55]
        if long_gaps:
            pen += 0.25 * len(long_gaps)
            notes.append(f"long pause {max(long_gaps):.2f}s")
        rate = len(ref_m) / max((voiced[-1] - voiced[0]) / 100, 0.1)
        if rate < 5.5 or rate > 10:
            pen += 0.2
            notes.append(f"rate {rate:.1f} mora/s")
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    if ref_m and not any(b.a + b.size >= len(ref_m) - 1 for b in blocks):
        pen += 0.3
        notes.append("ending not heard")
    durs = [x[1] - x[0] for x in t if x]
    if len(durs) >= 4 and max(durs) > 3.5 * float(np.median(durs)):
        pen += 0.15
        notes.append("stretched mora")
    flow_s = max(0.0, 1 - pen)
    return {"file": path, "asr_text": text, "asr": round(asr_s, 3), "accent": round(accent_s, 3), "phrases": rows,
            "flow": round(flow_s, 3), "flow_notes": notes, "total": round(100 * (0.4 * asr_s + 0.4 * accent_s + 0.2 * flow_s), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--texts", required=True)
    ap.add_argument("--fix")
    a = ap.parse_args()
    texts = {o["id"]: o["reading"] for o in json.load(open(a.texts, encoding="utf-8"))}
    fixes = json.load(open(a.fix, encoding="utf-8")) if a.fix else []
    res = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
    for p in a.wavs:
        if p in res:
            continue
        base = os.path.basename(p)
        sid = max((i for i in texts if base.startswith(i)), key=len, default=None)
        if sid is None:
            print("no text id for", p)
            continue
        try:
            res[p] = {"id": sid, **score(p, texts[sid], fixes)}
        except Exception as e:  # keep going: one broken take must not lose the batch
            res[p] = {"file": p, "id": sid, "error": repr(e), "total": 0}
        print(json.dumps(res[p], ensure_ascii=False), flush=True)
        json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
