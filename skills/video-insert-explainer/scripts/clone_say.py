"""Voice-clone TTS with Qwen3-TTS (Base model, Apache-2.0): one sentence, or a batch with the model loaded once.

usage: <tts-venv>/bin/python clone_say.py --project <project.json> --text "<sentence>" --out <out.wav> [--seed N]
       <tts-venv>/bin/python clone_say.py --project <project.json> --jobs <jobs.json>        # [{"text","out","seed"}]
       SHARD=k/n ... --jobs <jobs.json>   worker k of n takes every n-th job (run 2 workers side by side)

Refuses to run unless the project config has "rights": {"voice_clone_authorized": true} - set it per video,
only after the user explicitly chose to clone that voice; never copy it from an earlier project.
Config "tts": {"ref_wav", "ref_text", "model" (local snapshot dir or repo id), "device": "auto"|"mps"|"cpu"}.
Run offline with HF_HOME pointing at the downloaded weights and HF_HUB_OFFLINE=1; pass the snapshot DIRECTORY as
"model" (transformers still queries the Hub for a repo id even when offline).

Per take: the text gets a closing mark (the model tends to stop before the last mora); a take that ends
mid-sound is regenerated with seed+1 (up to 4 tries); the result is trimmed to 50 ms of lead-in, faded, padded
with 0.25 s of silence and written as 48 kHz mono s16. Existing outputs are skipped (safe to resume).
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

END_MARKS = "。．.！!？?…"
MAX_ATTEMPTS = 4
TAIL = 0.25


def frame_db(audio, sr, win):
    n = len(audio) // win
    return 20 * np.log10(np.sqrt((audio[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)


def with_closing_marks(text):
    text = text.strip()
    return text + ("。" if text and text[-1] in END_MARKS else "。。")


def ends_mid_sound(audio, sr):
    db = frame_db(audio, sr, int(sr * 0.01))
    kept = np.where(db > -70)[0]
    return len(kept) >= 3 and db[kept[-1] - 2: kept[-1]].max() > -30


def tidy(audio, sr):
    win = int(sr * 0.01)
    sounding = np.where(frame_db(audio, sr, win) > -60)[0]
    if len(sounding) == 0:
        return audio
    out = audio[max(0, sounding[0] - 5) * win: min(len(audio), (sounding[-1] + 1) * win)].copy()
    fade = int(sr * 0.02)
    out[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return np.concatenate([out, np.zeros(int(sr * TAIL), dtype=np.float32)])


def load_project(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("rights", {}).get("voice_clone_authorized") is not True:
        raise SystemExit("refusing: rights.voice_clone_authorized must be the boolean true for this project "
                         "(ask the user, per video, before cloning a voice)")
    root = os.path.dirname(os.path.abspath(path))
    t = cfg["tts"]
    p = lambda x: x if os.path.isabs(x) else os.path.join(root, x)  # noqa: E731
    model = t.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    return dict(ref_wav=p(t["ref_wav"]), ref_text=p(t["ref_text"]), model=p(model) if os.path.exists(p(model)) else model,
                device=t.get("device", "auto"), root=root)


class Voice:
    def __init__(self, conf):
        import torch
        from qwen_tts import Qwen3TTSModel

        self.torch = torch
        dev = conf["device"]
        if dev == "auto":
            dev = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = dev
        self.model = Qwen3TTSModel.from_pretrained(conf["model"], device_map=dev,
                                                   dtype=torch.float32 if dev == "cpu" else torch.float16)
        ref_text = open(conf["ref_text"], encoding="utf-8").read().strip()
        self.prompt = self.model.create_voice_clone_prompt(ref_audio=conf["ref_wav"], ref_text=ref_text)

    def say(self, text, out, seed):
        for attempt in range(MAX_ATTEMPTS):
            s = seed + attempt
            random.seed(s)
            np.random.seed(s)
            self.torch.manual_seed(s)
            wavs, sr = self.model.generate_voice_clone(text=with_closing_marks(text), language="Japanese",
                                                       voice_clone_prompt=self.prompt)
            audio = np.asarray(wavs[0], dtype=np.float32)
            if not ends_mid_sound(audio, sr):
                break
        if audio.size < sr * 0.2 or not np.isfinite(audio).all() or np.abs(audio).max() < 1e-3:
            raise RuntimeError(f"empty or invalid audio for {out}")
        audio = tidy(audio, sr)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            raw = tmp.name
        try:
            sf.write(raw, audio, sr)
            subprocess.run([os.environ.get("FFMPEG", "ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", raw,
                            "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", out + ".tmp.wav"], check=True)
            os.replace(out + ".tmp.wav", out)  # never leave a half-written take behind if stopped
        finally:
            os.unlink(raw)
        print(f"{out}\t{audio.size / sr:.2f}s\tseed={s}\tdevice={self.device}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--text")
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--jobs")
    a = ap.parse_args()
    conf = load_project(a.project)
    if a.jobs:
        k, n = map(int, os.environ.get("SHARD", "0/1").split("/"))
        jobs = [j for j in json.load(open(a.jobs, encoding="utf-8")) if not os.path.exists(os.path.join(conf["root"], j["out"]))][k::n]
    else:
        if not (a.text and a.out):
            ap.error("--text and --out, or --jobs")
        jobs = [{"text": a.text, "out": os.path.abspath(a.out), "seed": a.seed}]
    print(f"{len(jobs)} job(s)", flush=True)
    if not jobs:
        return 0
    voice = Voice(conf)
    for j in jobs:
        out = j["out"] if os.path.isabs(j["out"]) else os.path.join(conf["root"], j["out"])
        voice.say(j["text"], out, int(j.get("seed", 1234)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
