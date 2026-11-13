"""Assemble the full soundtrack (before loudnorm) at sample_rate stereo float: the source with word/line
replacements (anywhere on the source timeline, before or after the cut), split into part A | the insert
(narration, sound effects, interjections) | part C.

usage: python3 build_audio.py <project.json> <out.wav> [--extra-db X]

Boundaries are whole video frames (spf = sample_rate / fps samples each), so audio and video cannot drift:
  part A = source frames [0, cut_frame), insert = insert_frames, part C = source frames [cut_frame, base_frames).
Config "audio":
  narration_gain_db  gain for the placed narration (set it so the insert matches the source dialogue loudness)
  extra_db           added to narration AND sound effects, keeping their gap (CLI --extra-db overrides)
  replacements       [{"type": "word", "file", "start"|"end", "xfade": 0.02}  -> mute the source under the clip
                      {"type": "line", "file", "start", "xfade": 0.03}]      -> clip already contains the source
                                                                              context (line_replace.py); swap it in
Sound effects and interjection sounds come from the resolved events ("sfx", "interjections").
Interjections cut from the source keep their original level.
"""

import subprocess
import sys

import numpy as np
import soundfile as sf

from common import Project, ff


def load(path, sr):
    a, r = sf.read(path, dtype="float32", always_2d=True)
    if r != sr:
        raise SystemExit(f"{path}: {r} Hz, expected {sr}")
    return np.repeat(a, 2, axis=1) if a.shape[1] == 1 else a[:, :2]


def base_audio(path, sr):
    raw = subprocess.run([ff(), "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-f", "f32le", "-ac", "2",
                          "-ar", str(sr), "-"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def ramp(n, up):
    r = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    return r if up else 1.0 - r


def add(dst, clip, start, gain_db=0.0):
    end = min(len(dst), start + len(clip))
    if end > start:
        dst[start:end] += clip[: end - start] * 10 ** (gain_db / 20)


def main():
    pj = Project(sys.argv[1])
    out = sys.argv[2]
    cfg = pj.get("audio", {})
    extra = float(sys.argv[sys.argv.index("--extra-db") + 1]) if "--extra-db" in sys.argv else cfg.get("extra_db", 0.0)
    sr, spf = pj.sr, pj.spf
    at = lambda t: round(t * sr)  # noqa: E731
    orig = base_audio(pj.base, sr)
    a_len, i_len = pj.cut_frame * spf, pj.insert_frames * spf
    c_len = (pj.base_frames - pj.cut_frame) * spf
    if len(orig) < a_len + c_len:
        orig = np.concatenate([orig, np.zeros((a_len + c_len - len(orig), 2), np.float32)])

    # replacements work on the whole source timeline (before the split), like the plates
    src = orig[: a_len + c_len].copy()
    for rp in cfg.get("replacements", []):
        clip = load(pj.p(rp["file"]), sr)
        if rp["type"] == "line":
            # the clip covers [start, start+len) on the source timeline; cross-fade both edges into the source
            xf, s0 = at(rp.get("xfade", 0.03)), at(rp["start"])
            e0 = s0 + len(clip)
            seg = clip.copy()
            seg[:xf] = src[s0: s0 + xf] * ramp(xf, False) + seg[:xf] * ramp(xf, True)
            seg[-xf:] = seg[-xf:] * ramp(xf, False) + src[e0 - xf: e0] * ramp(xf, True)
            src[s0:e0] = seg
        else:
            # mute the source under the new word with fades centred on its edges (no gap of full silence)
            xf = at(rp.get("xfade", 0.02))
            hx = xf // 2
            s = at(rp["start"]) if "start" in rp else at(rp["end"]) - len(clip)
            m0, m1 = s - hx, s + len(clip) - hx
            src[m0: m0 + xf] *= ramp(xf, False)
            src[m0 + xf: m1] = 0
            src[m1: m1 + xf] *= ramp(xf, True)
            add(src, clip, s)
        if (s0 if rp["type"] == "line" else s) < a_len < (e0 if rp["type"] == "line" else s + len(clip)):
            print(f'WARNING replacement {rp["file"]} straddles the cut; move the cut or the replacement')
    part_a = src[:a_len].copy()
    fade = at(pj.get("audio.fade_at_cut", 0.05))
    part_a[-fade:] *= ramp(fade, False)

    ins = np.zeros((i_len, 2), np.float32)
    add(ins, load(pj.p(pj.get("narration.full")), sr), 0, cfg.get("narration_gain_db", 0.0) + extra)
    for fx in pj.events.get("sfx", []):
        clip = load(pj.p(fx["file"]), sr)
        for t in fx["times"]:
            add(ins, clip, at(t), fx.get("gain_db", 0.0) + extra)
    for ij in pj.events.get("interjections", []):
        if ij.get("sound"):
            add(ins, load(pj.p(ij["sound"]), sr), at(ij["t"]))

    part_c = src[a_len:].copy()
    part_c[:fade] *= ramp(fade, True)
    full = np.concatenate([part_a, ins, part_c])
    sf.write(out, full, sr, subtype="FLOAT")
    print(f"{out}: {len(full) / sr:.4f} s (A {a_len / sr:.3f} + insert {i_len / sr:.3f} + C {c_len / sr:.3f}); "
          f"peak {20 * np.log10(np.abs(full).max() + 1e-12):.1f} dBFS")


if __name__ == "__main__":
    main()
