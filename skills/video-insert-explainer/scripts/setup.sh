#!/bin/bash
# First-run environment for video-insert-explainer: three venvs and every model, downloaded side by side.
#
# usage: setup.sh [--home DIR] [--source URL --project DIR [--cookies-from-browser NAME]] [--no-demucs] [--install-tools]
#                 [--sequential] [--no-wait] [--status]
#
#   --home DIR       where venvs, models and job state live (default: $VIE_HOME, else ~/.cache/video-insert-explainer)
#   --source URL     also download URL into <project>/src/source.mp4 and transcode the 1080p30 work copy
#   --project DIR    project folder for --source (the work copy lands in <project>/work/base_1080p.mp4)
#   --cookies-from-browser NAME   passed to yt-dlp when the site answers "Sign in to confirm you're not a bot"
#   --no-demucs      skip the stem-separation venv and weights (only whole-line replacement needs them)
#   --install-tools  run `brew install` for missing ffmpeg / yt-dlp / uv instead of stopping
#   --sequential     run the jobs one after another in the foreground (slow; for low bandwidth or comparison)
#   --no-wait        start the jobs and return at once; check later with --status
#   --status         print the state of every job and wait until all have finished
#
# Every job runs detached (nohup) with <home>/setup/<job>/{log,exit,done}; a job whose `done` marker holds the
# checksum of its current command is skipped, so rerunning resumes after an interruption or a failure (downloads
# continue where they stopped) and a job whose command changed in a newer skill version runs again.
# A job that needs another one (a model warm-up needs its venv) waits for that job's exit file.
# A model download whose files stop growing for VIE_STALL_S seconds (default 120) is stopped and resumed, at most
# 3 times; then the job fails with "STALLED: <model>" in its log, which the final report prints.
# When everything succeeded, <home>/env.sh exports VIE_HOME, HF_HOME, TORCH_HOME, HF_HUB_OFFLINE=1,
# VIE_TTS_PY, VIE_ASR_PY, VIE_SEP_PY and VIE_TTS_MODEL (the Qwen3-TTS snapshot directory for tts.model).
# Exit status: 0 all done, 1 a job failed (its log tail is printed), 2 prerequisites missing.

set -u

HOME_DIR="${VIE_HOME:-$HOME/.cache/video-insert-explainer}"
SOURCE_URL="" PROJECT="" COOKIES="" DEMUCS=1 INSTALL=0 MODE=parallel WAIT=1 STATUS_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --home) HOME_DIR="$2"; shift 2 ;;
    --source) SOURCE_URL="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --cookies-from-browser) COOKIES="--cookies-from-browser '$2'"; shift 2 ;;
    --no-demucs) DEMUCS=0; shift ;;
    --install-tools) INSTALL=1; shift ;;
    --sequential) MODE=sequential; shift ;;
    --no-wait) WAIT=0; shift ;;
    --status) STATUS_ONLY=1; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ -n "$SOURCE_URL" ] && [ -z "$PROJECT" ]; then echo "--source needs --project" >&2; exit 2; fi

mkdir -p "$HOME_DIR"
HOME_DIR="$(cd "$HOME_DIR" && pwd)"
STATE="$HOME_DIR/setup"
mkdir -p "$STATE"
export VIE_HOME="$HOME_DIR" HF_HOME="$HOME_DIR/hf" TORCH_HOME="$HOME_DIR/torch"
TTS="$HOME_DIR/venvs/tts" ASR="$HOME_DIR/venvs/asr" SEP="$HOME_DIR/venvs/sep"

# ---- prerequisites -------------------------------------------------------------------------------------------
check_prereqs() {
  if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    echo "needs macOS on Apple silicon (mlx-whisper, MPS, macOS Vision OCR); found $(uname -s) $(uname -m)" >&2
    exit 2
  fi
  missing="" pkgs=""
  for t in ffmpeg ffprobe yt-dlp uv; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
  for t in yt-dlp uv; do command -v "$t" >/dev/null 2>&1 || pkgs="$pkgs $t"; done
  { command -v ffmpeg && command -v ffprobe; } >/dev/null 2>&1 || pkgs="ffmpeg$pkgs"
  pkgs="${pkgs# }"
  if [ -n "$missing" ]; then
    if [ "$INSTALL" = 1 ] && command -v brew >/dev/null 2>&1; then
      brew install $pkgs || exit 2
    else
      echo "missing:$missing" >&2
      echo "install with:  brew install $pkgs   (or rerun with --install-tools)" >&2
      exit 2
    fi
  fi
}

# ---- jobs: id | jobs it waits for | command --------------------------------------------------------------------
JOBS=""
add() { JOBS="$JOBS$1|$2|$3
"; }
add venv-tts "" "uv venv --allow-existing --python 3.12 '$TTS' && uv pip install --python '$TTS/bin/python' qwen-tts soundfile librosa pillow numpy && '$TTS/bin/python' -c 'import qwen_tts, PIL, librosa'"
add venv-asr "" "uv venv --allow-existing --python 3.12 '$ASR' && uv pip install --python '$ASR/bin/python' mlx-whisper pyopenjtalk-plus pyworld soundfile numpy 'setuptools<81'"
add model-tts "" "hfdl Qwen/Qwen3-TTS-12Hz-1.7B-Base"
add model-tokenizer "" "hfdl Qwen/Qwen3-TTS-Tokenizer-12Hz"
add model-whisper "" "hfdl mlx-community/whisper-large-v3-turbo"
add warm-asr "venv-asr" "'$ASR/bin/python' -c 'import mlx_whisper, pyworld, pyopenjtalk; print(pyopenjtalk.g2p(\"テスト\"))'"
if [ "$DEMUCS" = 1 ]; then
  add venv-sep "" "uv venv --allow-existing --python 3.12 '$SEP' && uv pip install --python '$SEP/bin/python' demucs soundfile 'torch<2.9' 'torchaudio<2.9'"
  add model-demucs "venv-sep" "'$SEP/bin/python' -c 'from demucs.pretrained import get_model; get_model(\"htdemucs_ft\")'"
fi
if [ -n "$SOURCE_URL" ]; then
  mkdir -p "$PROJECT"
  P="$(cd "$PROJECT" && pwd)"
  add source "" "mkdir -p '$P/src' '$P/work' && cd '$P' && { [ -s src/source.mp4 ] || yt-dlp -N 8 --http-chunk-size 10M $COOKIES -f 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b' --merge-output-format mp4 --write-auto-subs --sub-langs ja -o 'src/source.%(ext)s' '$SOURCE_URL'; } && { [ -s work/base_1080p.mp4 ] || { dec=\$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 src/source.mp4); [ \"\$dec\" = av1 ] && dec='-c:v libdav1d' || dec=''; ffmpeg -hide_banner -loglevel error -y \$dec -i src/source.mp4 -vf 'scale=1920:1080:flags=lanczos,fps=30' -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -ac 2 work/base_1080p.part.mp4 && mv work/base_1080p.part.mp4 work/base_1080p.mp4; }; }"
fi

ids() {
  if [ "$STATUS_ONLY" = 1 ]; then ls "$STATE"; else printf '%s' "$JOBS" | cut -d'|' -f1; fi
}
deps_of() { printf '%s' "$JOBS" | awk -F'|' -v id="$1" '$1 == id { print $2 }'; }
cmd_of() { printf '%s' "$JOBS" | awk -v id="$1" 'index($0, id "|") == 1 { sub("^[^|]*\\|[^|]*\\|", ""); print }'; }

cmd_hash() { cmd_of "$1" | cksum | cut -d' ' -f1; }

running() { [ -f "$STATE/$1/pid" ] && [ ! -f "$STATE/$1/exit" ] && kill -0 "$(cat "$STATE/$1/pid")" 2>/dev/null; }

write_runner() {
  d="$STATE/$1"
  mkdir -p "$d"
  {
    echo 'cd "$(dirname "$0")"'
    cat <<'EOF'
# A transfer was seen to stall for good (no bytes, no exit); restart it when its files stop growing.
# hf download resumes partial files, so a restart loses nothing.
hfdl() {
  dir="$HF_HOME/hub/models--$(echo "$1" | sed 's|/|--|g')"
  for try in 1 2 3; do
    uvx --from huggingface_hub hf download "$1" & pid=$!
    last=x still=0
    while kill -0 $pid 2>/dev/null; do
      sleep 5
      now=$(du -sk "$dir" "$HF_HOME/xet" 2>/dev/null | awk '{ s += $1 } END { print s }')
      if [ "$now" = "$last" ]; then still=$((still + 5)); else still=0; last=$now; fi
      if [ $still -ge "${VIE_STALL_S:-120}" ]; then
        echo "no progress on $1 for ${VIE_STALL_S:-120} s; stopping it (attempt $try of 3)"
        pkill -KILL -P $pid; kill -KILL $pid  # a wedged transfer may never act on TERM
        break
      fi
    done
    wait $pid && return 0
  done
  echo "STALLED: the download of $1 made no progress 3 times; check the network (or set HF_TOKEN) and rerun setup.sh"
  return 1
}
EOF
    for dep in $(deps_of "$1"); do
      echo "while [ ! -f '$STATE/$dep/exit' ]; do sleep 2; done"
      echo "[ \"\$(cat '$STATE/$dep/exit')\" = 0 ] || { echo 'waited for $dep, which failed'; exit 3; }"
    done
    echo 'date +%s > start'
    echo "( $(cmd_of "$1") )"
    echo "rc=\$?; date +%s > end; [ \$rc = 0 ] && echo '$(cmd_hash "$1")' > done; exit \$rc"
  } > "$d/run.sh"
}

launch() {
  for id in $(ids); do
    d="$STATE/$id"
    if [ -f "$d/done" ] && [ "$(cat "$d/done")" = "$(cmd_hash "$id")" ]; then continue; fi
    rm -f "$d/done"  # finished with an older command (the skill changed what this job installs): run it again
    if running "$id"; then continue; fi
    rm -f "$d/exit" "$d/start" "$d/end"
    write_runner "$id"
    if [ "$MODE" = sequential ]; then
      echo "== $id"
      sh "$d/run.sh" > "$d/log" 2>&1; echo $? > "$d/exit"
    else
      nohup sh -c "sh '$d/run.sh'; echo \$? > '$d/exit'" > "$d/log" 2>&1 < /dev/null &
      echo $! > "$d/pid"
    fi
  done
}

state_of() {
  d="$STATE/$1"
  if [ -f "$d/done" ]; then
    if [ -f "$d/start" ] && [ -f "$d/end" ]; then echo "done $(( $(cat "$d/end") - $(cat "$d/start") ))s"; else echo "done"; fi
  elif [ -f "$d/exit" ]; then echo "FAILED (exit $(cat "$d/exit"))"
  elif running "$1"; then echo running
  else echo "not started"; fi
}

report() {
  for id in $(ids); do printf '  %-16s %s\n' "$id" "$(state_of "$id")"; done
}

wait_all() {
  t0=$(date +%s) last=""
  while :; do
    pending=0
    for id in $(ids); do
      [ -f "$STATE/$id/exit" ] || [ -f "$STATE/$id/done" ] || { running "$id" && pending=1; }
    done
    now="$(report)"
    if [ "$now" != "$last" ]; then echo "[$(( $(date +%s) - t0 ))s]"; echo "$now"; last="$now"; fi
    [ $pending = 0 ] && break
    sleep 5
  done
}

write_env() {
  snap=$(ls -d "$HF_HOME"/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base/snapshots/*/ 2>/dev/null | head -1)
  snap="${snap%/}"
  cat > "$HOME_DIR/env.sh" <<EOF
export VIE_HOME='$HOME_DIR'
export HF_HOME='$HF_HOME'
export TORCH_HOME='$TORCH_HOME'
export HF_HUB_OFFLINE=1
export VIE_TTS_PY='$TTS/bin/python'
export VIE_ASR_PY='$ASR/bin/python'
export VIE_SEP_PY='$SEP/bin/python'
export VIE_TTS_MODEL='$snap'
EOF
  echo "env: source '$HOME_DIR/env.sh'"
  echo "project.json: \"tts\": {\"python\": \"$TTS/bin/python\", \"model\": \"$snap\", ...}"
}

finish() {
  failed=0
  for id in $(ids); do
    if [ ! -f "$STATE/$id/done" ]; then
      failed=1
      echo "---- $id: $(state_of "$id"); last lines of $STATE/$id/log"
      tail -n 15 "$STATE/$id/log" 2>/dev/null
    fi
  done
  [ $failed = 0 ] || { echo "rerun setup.sh to retry the failed jobs (finished ones are skipped)"; exit 1; }
  write_env
  exit 0
}

if [ "$STATUS_ONLY" = 1 ]; then wait_all; finish; fi
check_prereqs
launch
if [ "$MODE" = sequential ]; then report; finish; fi
if [ "$WAIT" = 0 ]; then report; echo "jobs started; check with: $0 --home '$HOME_DIR' --status"; exit 0; fi
wait_all
finish
