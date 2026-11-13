"""Shared helpers: project config, frame math, ffmpeg, fonts, colors, easing.

Every script takes the project config (see project.example.json). Relative paths in the config are resolved
against the config file's directory. Frame math lives only here so the video and audio sides cannot drift:

  cut_frame     first source frame shown AFTER the insert (the freeze frame is cut_frame - 1)
  insert_frames round(insert_len * fps), insert_len from the resolved events JSON
  base_frames   frame count of the work copy (ffprobe)
  spf           audio samples per video frame (sample_rate / fps, must be an integer)
"""

import json
import math
import os
import shutil
import subprocess

from PIL import ImageFont

W, H = 1920, 1080


def ff(name="ffmpeg"):
    path = os.environ.get(name.upper()) or shutil.which(name)
    if not path:
        raise SystemExit(f"{name} not found (set ${name.upper()})")
    return path


class Project:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.root = os.path.dirname(self.path)
        with open(self.path, encoding="utf-8") as f:
            self.cfg = json.load(f)
        self.fps = int(self.cfg.get("fps", 30))
        self.sr = int(self.cfg.get("sample_rate", 48000))
        if self.sr % self.fps:
            raise SystemExit(f"sample_rate {self.sr} is not a multiple of fps {self.fps}")
        self.spf = self.sr // self.fps
        self.source_fps = float(self.cfg["source"].get("measured_fps", self.fps))
        self.cut_frame = math.ceil(self.cfg["cut"]["time"] * self.fps - 1e-6)
        self._base_frames = None
        self._events = None

    def p(self, rel):
        """Config-relative path -> absolute path."""
        return rel if os.path.isabs(rel) else os.path.join(self.root, rel)

    def get(self, dotted, default=None):
        cur = self.cfg
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    @property
    def base(self):
        return self.p(self.cfg["source"]["work_copy"])

    @property
    def base_frames(self):
        if self._base_frames is None:
            out = subprocess.run([ff("ffprobe"), "-v", "error", "-select_streams", "v:0", "-count_packets",
                                  "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", self.base],
                                 check=True, capture_output=True, text=True).stdout.strip()
            self._base_frames = int(out.split(",")[0])
        return self._base_frames

    @property
    def events(self):
        if self._events is None:
            with open(self.p(self.cfg["events"]), encoding="utf-8") as f:
                self._events = json.load(f)
        return self._events

    @property
    def insert_frames(self):
        return round(self.events["insert_len"] * self.fps)

    def out_frame(self, axis, t):
        """Output frame number for a time on the source axis ('o') or the insert axis ('T')."""
        if axis == "T":
            return self.cut_frame + round(t * self.fps)
        k = round(t * self.fps)
        return k if k < self.cut_frame else k + self.insert_frames


FLASH_HALF = 0.08  # white flash: rises over the last 0.08 s of the insert, falls over the first 0.08 s after it

_fonts = {}


def font(project_or_pattern, weight, size):
    pattern = project_or_pattern if isinstance(project_or_pattern, str) else \
        project_or_pattern.get("style.font_pattern", "/System/Library/Fonts/ヒラギノ角ゴシック W{}.ttc")
    key = (pattern, weight, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(pattern.format(weight), size)
    return _fonts[key]


def hexrgb(h, a=255):
    h = h.lstrip("#")
    return tuple(int(h[i: i + 2], 16) for i in (0, 2, 4)) + (a,)


def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_in_out(x):
    x = clamp01(x)
    return 3 * x * x - 2 * x * x * x


def ease_out(x):
    return 1 - (1 - clamp01(x)) ** 3


def ease_in(x):
    return clamp01(x) ** 3


def back(c1):
    c3 = c1 + 1
    return lambda x: 1 + c3 * (clamp01(x) - 1) ** 3 + c1 * (clamp01(x) - 1) ** 2


def back_with_overshoot(target):
    """ease-out-back whose peak overshoots by `target` (e.g. 0.06 = 6%)."""
    lo, hi = 0.0, 3.0
    for _ in range(60):
        mid = (lo + hi) / 2
        peak = max(back(mid)(i / 1000) for i in range(1001))
        lo, hi = (mid, hi) if peak < 1 + target else (lo, mid)
    return back(lo)


def lerp(a, b, r):
    return a + (b - a) * r


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)
