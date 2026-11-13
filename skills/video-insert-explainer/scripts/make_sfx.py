"""Synthesize the four sound effects (no external assets): chime_up, chime_down, pop, flip - 48 kHz stereo WAVs.

usage: python3 make_sfx.py <outdir>
Levels are set later per effect in the events ("sfx[].gain_db"); aim for about 6 LU under the narration.
"""

import os
import sys

import numpy as np
import soundfile as sf

SR = 48000


def tone(freqs, dur, decay):
    t = np.arange(int(SR * dur)) / SR
    y = sum(np.sin(2 * np.pi * f * t) * (0.5 ** i) for i, f in enumerate(freqs))
    return y * np.exp(-t * decay)


def seq(notes, step, decay):
    out = np.zeros(int(SR * (step * len(notes) + 1.2)))
    for i, f in enumerate(notes):
        y = tone([f, 2 * f, 3 * f], 1.2, decay)
        s = int(SR * step * i)
        out[s: s + len(y)] += y
    return out


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(int(SR * 0.18))
    flip = np.convolve(noise, np.ones(24) / 24, mode="same") * np.exp(-np.arange(len(noise)) / SR * 22)
    effects = {
        "chime_up": seq([659.3, 830.6, 987.8, 1318.5], 0.28, 3.0),
        "chime_down": seq([1318.5, 987.8, 830.6, 659.3], 0.28, 3.0),
        "pop": tone([880, 1760], 0.12, 40) * np.linspace(1.4, 0.6, int(SR * 0.12)),
        "flip": flip,
    }
    for name, y in effects.items():
        fade = int(SR * 0.005)
        y[:fade] *= np.linspace(0, 1, fade)
        y = 0.5 * y / (np.abs(y).max() + 1e-9)
        sf.write(os.path.join(out, f"{name}.wav"), np.stack([y, y], axis=1).astype(np.float32), SR, subtype="PCM_16")
        print(os.path.join(out, f"{name}.wav"), f"{len(y) / SR:.2f}s")


if __name__ == "__main__":
    main()
