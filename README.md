# video-insert-explainer

A [Claude Code](https://claude.com/claude-code) skill that pauses an existing video at a chosen moment, inserts a narrated slide explainer (zooms, markers, page turns, subtitles) in the voice of a character from the video, and returns to the video.

Optionally it adds an analogy gag: an object in the video is reframed as the thing being announced (worked example: a neighborhood circular, 回覧板, becomes a feature-update notice, 機能追加), and that word is replaced everywhere in the source — burned-in captions are covered with drawn plates, and the spoken word is re-voiced with a voice clone.

It covers download, cut-point search, script, voice clone (Qwen3-TTS), Japanese pitch-accent repair, events-driven rendering, loudness normalization, and QA.

## Contents

- `skills/video-insert-explainer/SKILL.md` — the skill (English)
- `skills/video-insert-explainer/scripts/` — the pipeline scripts; `scripts/examples/` holds fictional example configs
- `skills-ja/video-insert-explainer/SKILL.ja.md` — the same skill in Japanese (for human readers)

## Install

```sh
git clone https://github.com/topaz2/video-insert-explainer.git
cp -R video-insert-explainer/skills/video-insert-explainer ~/.claude/skills/
```

Then ask Claude Code something like "insert these slides into this video right after <scene>, narrated by <character>".

## Requirements

macOS (Apple silicon), ffmpeg, yt-dlp, uv, Python with Pillow / numpy / soundfile / librosa. See the Environment section of `SKILL.md` for the TTS and ASR environments.

## Rights

- Download and edit only videos you are allowed to use. Outputs stay local; publishing is your decision.
- Voice cloning runs only when `rights.voice_clone_authorized` is set to `true` in the project config. Do not clone a voice without the right to do so, and never produce output that passes for a real person's statement.
- macOS `say` voices are for timing drafts only.

## License

MIT (see `LICENSE`). Models and tools used by the pipeline keep their own licenses (Qwen3-TTS: Apache-2.0; whisper: MIT; demucs: MIT).

---

# video-insert-explainer（日本語）

既存の動画を好きな場面で止めて、その動画の登場人物の声でスライドを解説し、また動画に戻る——という動画を作るための Claude Code のスキルです。

動画の中の物を、伝えたい中身に見立てる演出もできます（作例：回覧板を「機能追加」のお知らせに見立てる）。そのときは、元動画の字幕とセリフの語をすべて差し替えます。

インストールは上の Install を参照してください。使い方は「この動画の〇〇の場面のあとに、このスライドを入れて、〇〇の声で解説して」のように頼みます。詳しくは `skills-ja/video-insert-explainer/SKILL.ja.md` にあります。
