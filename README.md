# video-insert-explainer

A [Claude Code](https://claude.com/claude-code) skill that pauses an existing video at a chosen moment, inserts a narrated slide explainer (zooms, markers, page turns, subtitles) in the voice of a character from the video, and returns to the video.

Optionally it adds an analogy gag: an object in the video is reframed as the thing being announced (worked example: a neighborhood circular becomes a feature-update notice), and that word is replaced everywhere in the source — burned-in captions are covered with drawn plates, and the spoken word is re-voiced with a voice clone.

It covers download, cut-point search, script, voice clone (Qwen3-TTS), Japanese pitch-accent repair, events-driven rendering, loudness normalization, and QA.

## Contents

- `skills/video-insert-explainer/SKILL.md` — the skill (English)
- `skills/video-insert-explainer/scripts/` — the pipeline scripts; `scripts/examples/` holds a fictional example config (`project.example.json`) and the default-video preset (`default-video.json`, values measured on the default video)
- `skills-ja/video-insert-explainer/SKILL.ja.md` — the same skill in Japanese (for human readers)

## Install

```sh
git clone https://github.com/topaz2/video-insert-explainer.git
cp -R video-insert-explainer/skills/video-insert-explainer ~/.claude/skills/
```

Then ask Claude Code something like "insert these slides into this video right after <scene>, narrated by <character>".
If you name no video, the skill uses its default video (see Special Thanks) with the ready preset, and asks only for the slides.

## Requirements

macOS (Apple silicon), ffmpeg, yt-dlp, uv, Python with Pillow / numpy / soundfile / librosa. See the Environment section of `SKILL.md` for the TTS and ASR environments.

## Rights

- Download and edit only videos you are allowed to use; this includes the default video. Outputs stay local; publishing is your decision.
- Voice cloning runs only when `rights.voice_clone_authorized` is set to `true` in the project config. Do not clone a voice without the right to do so, and never produce output that passes for a real person's statement.
- macOS `say` voices are for timing drafts only.

## Special Thanks

The default preset (`scripts/examples/default-video.json`) is built on a video by the YouTube channel
**AI動画ラボコイコイ** (@AiLabokoikoi, https://www.youtube.com/channel/UCJaIMlyiJSBSgOJVieE_2Hw):
https://www.youtube.com/watch?v=fxS4P6IhKxs. Thank you for the wonderful video.

The video itself is not included in or redistributed by this repository; the preset only holds measured times,
positions and colors. Any use of the video is subject to the creator's terms. This credit does not imply the
creator's permission or endorsement.

## License

MIT (see `LICENSE` and `NOTICE`). Models and tools used by the pipeline keep their own licenses (Qwen3-TTS: Apache-2.0; whisper: MIT; demucs: MIT).
