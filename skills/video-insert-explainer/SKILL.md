---
name: video-insert-explainer
description: "One-shot pipeline that pauses an existing video at a chosen moment, inserts a narrated slide explainer (zooms, markers, page turns, subtitles) and returns to the video, optionally with an analogy gag: an object in the video is reframed as the thing being announced and its word is replaced everywhere in the source (burned-in captions covered with Pillow plates, the spoken word re-voiced with a voice clone of the on-screen character). Covers download, cut-point search, script, voice clone (Qwen3-TTS), pitch-accent repair, events-driven rendering, loudness, QA. Triggers: insert slides into a video with narration, explain an announcement inside a video, narrate in a character's voice, replace a word in a video's captions and speech, 「動画の途中にスライドを挟んで解説」「回覧板みたいに見立てて」「〇〇に見立てて」「キャラの声でナレーション」「動画の字幕とセリフの言葉を差し替えて」. Not for finishing a pptx deck (themed-deck-finishing) or E2E verification videos (playwright-verification-video)."
---

# Video Insert Explainer

Pause a video right after a chosen moment, explain something on slides in the voice of a character from
the video, and return to the video. The worked example of the analogy: a scene where a character delivers a
neighborhood circular becomes the delivery of a feature-update notice; every mention of the circular in the
source - captions and speech - is replaced by the feature-update word, and the delivering character explains
the slides. `scripts/examples/` shows the words themselves: `sentences.json` (the reading text, with the
katakana long-vowel spelling of the key word), `subtitles.json` (the display text) and the plates in
`project.example.json`.

All scripts live in `${CLAUDE_SKILL_DIR}/scripts/` (the `scripts/` folder next to this SKILL.md, wherever the
skill or plugin is installed); the bare script names below are in that folder. They read one project config
(`scripts/examples/project.example.json` has fictional values, `default-video.json` the measured values of the
default video; each script's docstring is its contract).

## Rights gate (before any download or voice work)

- Download only the URL the user gave, or the default video below when the user names none; the output stays a
  local file and the user decides on any publication.
- Cloning a person's or character's voice needs the user's explicit choice for THIS video: set
  `rights.voice_clone_authorized: true` in this project's config. `clone_say.py` refuses any other value.
  Never copy the flag from an earlier project. Never produce output that passes for a real person's statement.
- macOS `say` voices are for timing drafts only (personal, non-commercial license) - never in a deliverable.
- Record in the edit list where every asset came from and how far it may be used (source video, slides,
  cloned voice, interjections cut from the source, synthesized sound effects).

## Inputs (ask once, together)

| Input | Example |
|---|---|
| Source video URL | a public video the user names |
| Insert point | "right after the circular is handed over" (a scene description, not a time) |
| Slide source | images of the announcement slides (fetch them yourself from where the user points) |
| Analogy / word mapping | circular → feature update (object in the video → thing announced); empty = no gag |
| Narrator | which on-screen character speaks; their clean lines become the clone reference |
| Output | default 1920x1080, 30 fps, H.264 crf 18, AAC 48 kHz, -14 LUFS / -1 dBTP, local mp4 |

## Default video (when the user names no video)

Unless the user names another video, build on https://www.youtube.com/watch?v=fxS4P6IhKxs (channel
@AiLabokoikoi, https://www.youtube.com/channel/UCJaIMlyiJSBSgOJVieE_2Hw) with the ready preset
`scripts/examples/default-video.json`. Ask only for the slides (and anything genuinely missing, such as which
announcement they describe); the insert point, the circular → feature-update analogy, the narrator and every
replacement site are already in the preset. The rights gate still applies: ask the user to confirm voice cloning
for this video and set `rights.voice_clone_authorized: true` in the project copy, never in the preset.

What the preset holds (measured on the source; `default_video` carries the recipes, `plates` / `audio` / `checks`
are read by the scripts as is):
- Cut 51.65 s (freeze frame 51.633), right after the delivery scene; the insert returns to 51.65 with the white flash.
- Characters by description: narrator = the white-haired person in patterned clothes who delivers the item;
  listener = the person in the green sweater who receives it.
- Voice references (`default_video.references`): calm = 48.50-50.02 + 0.30 s silence + 54.45-55.25 (mix, no
  music there); shout = 19.80-21.60, 42.20-42.55, 43.30-43.80 joined with 0.30 s gaps, from the demucs vocals of
  the 17.0-60.0 excerpt.
  Cut each part with `ffmpeg -ss <s> -t <len>`, join, and write the transcript from `text` next to it.
- Spoken replacements: S1 = whole shouted line (source line 19.80-21.50, context 18.30-23.00, new line measured
  19.83-21.67) via `clone_say.py` with the shout reference (a copy of project.json whose `tts.ref_*` point at it),
  then `line_replace.py --stem-start 17.0 --context 18.30 23.00 --line 19.80 21.50`; S2 = word in 48.40-49.00
  read inside `carrier_text` with the calm reference, `word_tools.py extract`, then
  `fit_word.py --slot 0.60 --max-tempo 1.10 --match <work copy> --range 48.50 49.00`.
- Burned-in text: plates V1-V6 (mission banner, two captions, a split-screen caption, a zooming prompt field in
  three stages, an inset caption).
- Interjections (`default_video.interjections`): the listener's two short reactions, cut with the
  `interjection_recipe` commands (sound with 10/30 ms fades; face inset crop scaled to 384x216 with a 6 px white
  border); in the events use `pip_pos` [1500, 620] and caption color #8FD694.
- Loudness: the source dialogue just before the cut (40.0-51.6, `qa.dialogue`) measures -13.1 LUFS on the work copy.
The slides and their names, wording and people stay out of the preset; it carries the video side only.

## Environment

- ffmpeg/ffprobe (this build may lack drawtext/subtitles - all text is drawn with Pillow), yt-dlp, uv.
- Media scripts: any Python with Pillow, numpy, soundfile, librosa (the TTS venv below has them).
- TTS venv: `uv venv --python 3.12 tts/.venv` + `uv pip install -U qwen-tts "huggingface_hub[cli]" soundfile librosa`,
  then `HF_HOME=tts/hf hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base` and `... Qwen/Qwen3-TTS-Tokenizer-12Hz`
  (Apache-2.0). Run with `HF_HOME` set and `HF_HUB_OFFLINE=1`; `tts.model` is the snapshot directory.
- ASR/accent venv: `mlx-whisper pyopenjtalk-plus pyworld soundfile numpy` (whisper large-v3-turbo).
- Stem separation (only for line replacement): separate venv with `demucs soundfile "torch<2.9" "torchaudio<2.9"`.
- Run long jobs (transcode, TTS batches, demucs, render) detached with `nohup ... ; echo $? > exit.txt`.

## Pipeline

0. **Project folder.** Make a work folder and copy `scripts/examples/project.example.json` (as `project.json`;
   for the default video copy `default-video.json` instead), `sentences.json`, `subtitles.json` and
   `events.template.json` into it; replace every example value (with the preset, only the slide and narration side).
   Leave `rights.voice_clone_authorized` false; set it to true only after the user chose to clone the voice.
1. **Download + work copy.** `yt-dlp -f "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b" --merge-output-format mp4 --write-auto-subs --sub-langs ja -o "src/source.%(ext)s" <url>`.
   Transcode once: `ffmpeg -c:v libdav1d -i src/source.mp4 -vf "scale=1920:1080:flags=lanczos,fps=30" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -ac 2 work/base_1080p.mp4`.
   Every later step reads the work copy (seeking 4K AV1 per frame is too slow). Measure caption times on the
   source's own frame grid (`source.measured_fps`, often 60) - the 30 fps work copy can hide a 1-frame caption.
2. **Cut point.** `find_cut.py <work copy> <t0> <t1> <dir> --band x,y,w,h` gives a 0.1 s contact sheet, a
   per-frame caption-band stack and 50 ms RMS. Cut inside a dialogue valley; the freeze frame is the last
   frame without the next caption (`cut.time` rounds up to the first frame after it). Cutting mid-shot needs
   the white flash on the way back (built in), or the jump reads as a glitch.
3. **Find every occurrence of the replaced word** (analogy only). Spoken: whisper with word timestamps over the
   whole audio (re-transcribe music-heavy stretches in short parts). On screen: `find_text.py <video> <dir> --words ...`
   (macOS Vision every 0.1 s via `ocr_frames.swift`; 0.5 s sampling misses short captions) lists runs with
   sampled first/last time and box; then measure each run's exact first/last frame with `find_cut.py --band`.
   Search the reading variants too. List them as S1.. (spoken) and V1.. (visual) with times, boxes, speaker.
   Where a caption shows the word with no audible speech, confirm by cross-correlating the spoken word's audio
   against that stretch before deciding there is nothing to re-voice.
4. **Script and edit list.** Narrator speaks in the character's own register; one page of narration per slide;
   the closing line hands back to the source scene. Keep three texts apart: the TTS reading
   (`sentences.json`), the subtitles (`subtitles.json`: at most 28 characters per line, the full-width slash
   marks the break, no spaces around Latin letters or digits) and the slides. Write down which name our added
   wording uses for the object. **Gate:** QA reviews script + edit list (cut point, timing collisions, every
   line over 28 characters has a break, facts match the slides) before any voice work.
5. **Reference + voice.** Cut 5-15 s of the narrator's cleanest lines (no music; use demucs vocals if needed;
   a shouted line needs its own shouted reference) with an exact transcript. Draft timing with `--engine say`,
   then `build_narration.py --engine clone`. `clone_say.py` retries a take that stops mid-sound (seed+1),
   trims the head and adds 0.25 s of tail. For batches use `--jobs` with `SHARD=0/2` and `SHARD=1/2` in
   parallel: 2 workers was the observed optimum on one Apple-silicon machine (4 workers were not faster).
6. **Pitch-accent repair.** Generate several seeds and spelling variants per sentence, `score.py` them
   (whisper reading + pyopenjtalk accent per phrase + flow), then `listen_page.py` for the user to pick;
   picks go into `narration.take`. What fixed misreads and wrong accents:
   - katakana with long-vowel marks for the problem word or name (the reading spelled as it should sound;
     `examples/sentences.json` spells the feature-update word this way);
   - kana for words the model misreads, but keep kanji where kana makes it read a homophone instead
     (the feature-update word in hiragana was heard as the homophone meaning "yesterday");
   - for a key word that must be said alone, say it inside a short sentence and cut it out
     (`word_tools.py extract`); measure its shape with `word_tools.py shape --pattern`.
   **The user's ears decide** - scores only order the candidates.
7. **Spoken replacements.** Word: `fit_word.py` (trim, at most 1.1x speed-up, a shout tolerated 1.25x; level
   matched to the source word) → `audio.replacements` type `word`. If it still does not fit, or the line is
   shouted, regenerate the whole line over the accompaniment: demucs on an excerpt, then `line_replace.py`
   → type `line`. Edges are 20-30 ms cross-fades, never hard mutes (a full-silence gap clicks).
   Whisper the replaced stretch in context; then ask the user to listen.
8. **Caption plates.** `plates.py` from config `plates`: opaque plates (feather outward only, so nothing shows
   through), colors / weight / size measured from the frames, the whole line redrawn when the new word is
   longer, `stages` with per-frame interpolation for text that zooms with the picture. Plates are applied on
   the source timeline before the cut. `check_plates.py <group>` for before/first/middle/last/after strips.
9. **Events.** Copy `examples/events.template.json`; every time is an anchor expression on the narration
   (`=n2_01.s`, `=T2+0.4`), so re-voicing never needs hand-copied times. `resolve_events.py` runs the
   template's `checks`. Timing rules: zoom back to full view before a marker or page turn starts (both use
   full-view coordinates); badges hide while zoomed; badges and notes sit in an empty area of the full view,
   never over slide text, with a faint shadow on white; a note shows only while the sentence about its
   content is spoken; page turns and interjections fall in narration gaps (the template's checks test that an
   interjection neither starts before the previous voice ends nor runs into the next one);
   a blink frame is drawn outside an existing red frame or it merges with it; interjections reuse the
   listener's own short reactions cut from the source (picture + voice), never a new voice.
10. **Telops and subtitles.** `make_telops.py`: subtitles start at the measured voice onset (-35 dB; -45 dB
    trips on head noise), heading fades 0.2 s, interjection captions sit above the face inset.
    `preview.py` gives a browser sketch of timing and wording before the long render.
11. **Audio and loudness.** The source goes silent during the insert (the sudden quiet plus chime is part of
    the joke). Measure the source dialogue near the cut and the narration with `loudness.py measure`; set
    `audio.narration_gain_db` so they match; sound effects ~6 LU under the narration (`make_sfx.py` makes them).
    Master with two-pass linear loudnorm; if it falls back to dynamic, fix the mix gains instead of accepting it.
12. **Render.** `build_all.py project.json out/final.mp4` (resolve → plates → telops → audio → loudnorm →
    insert → assemble → checks). It never overwrites an existing output.
13. **QA.** `check_output.py` (frame count, A/V lag at speech moments, loudness of whole/insert/source dialogue,
    black/freeze stretches) and `verify_frames.py` sheets from config `checks` (before/first/middle/last/after
    of each plate and replacement, the cut and return, every effect). The first frame after the white flash
    must be the source picture, with no blurred background left over (the flash fades out on the source side).
    A detected black or frozen stretch is a defect only if the source has none at the same place.
    QA re-transcribes the insert and the
    replaced lines, compares subtitles with the script character by character, and lists what needs ears.

## Review gates and the human ear

| Gate | Who | What |
|---|---|---|
| Script + edit list | QA | collisions, missing breaks, facts vs slides, cut point evidence |
| Voice choice | user (ears) | clone likeness, candidate picks on the listening page |
| Replaced words | user (ears) | the new word is heard as intended, in context; seams |
| Final | QA, then user | frame sheets, sync, loudness; then naturalness, pauses, chime onset |

Team shape that worked: planner (scene, script, edit list), editor (download, voice, render), QA (reviews and
final check). The lead routes; only the user can judge how the voice sounds.

## Scripts

| Script | Role |
|---|---|
| `common.py`, `textlib.py` | config, single source of frame math (cut / insert / base frames, samples per frame), Pillow text |
| `find_cut.py` | contact sheet, caption-band stack, RMS table |
| `find_text.py`, `ocr_frames.swift` | on-screen word search (macOS Vision OCR) |
| `build_narration.py`, `clone_say.py` | clips → `timeline.json` (with voice onsets) → `narration_full.wav` |
| `score.py`, `word_tools.py`, `listen_page.py` | accent scoring, key-word shape / extraction, take picker page |
| `fit_word.py`, `line_replace.py` | spoken word / whole-line replacements |
| `plates.py`, `filter_template.py`, `check_plates.py` | caption cover plates and their checks |
| `resolve_events.py`, `make_telops.py`, `build_insert.py`, `preview.py` | insert schedule, captions, render, browser sketch |
| `build_audio.py`, `loudness.py`, `make_sfx.py` | soundtrack, loudness, sound effects |
| `assemble.py`, `build_all.py`, `check_output.py`, `verify_frames.py` | final assembly, one-command build, QA |

## Done means

The mp4 plays end to end; `check_output.py` exits 0; every plate and replacement passed its frame strip;
the subtitles equal the script; QA's final report is clean; the user has listened to the voice and replaced
words; the asset/rights table is written. Report the output path, length and what was left to taste.

## Credit

The default preset is built on a video by the YouTube channel @AiLabokoikoi
(https://www.youtube.com/channel/UCJaIMlyiJSBSgOJVieE_2Hw). The video is not redistributed; its use is subject to
the creator's terms, and the credit does not imply the creator's permission or endorsement.
