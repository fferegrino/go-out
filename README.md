# go-out

Build a video with a randomised soundtrack: songs from a folder are shuffled, concatenated to match the video length, and merged with the original video. The **current song title** is shown in the **top-left corner** and updates when each track starts.

## Requirements

### System

| Tool | Purpose |
|------|---------|
| [FFmpeg](https://ffmpeg.org/) (`ffmpeg`, `ffprobe`) | Audio export, final encode, on-screen titles |
| [Chromaprint](https://acoustid.org/chromaprint) (`fpcalc`) | AcoustID fingerprinting (only with `--identify`) |

On macOS, install the **full** FFmpeg build (not the minimal Homebrew formula):

```bash
brew install ffmpeg-full chromaprint
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
```

Confirm `drawtext` is available (recommended for fast label rendering):

```bash
ffmpeg -filters 2>&1 | grep drawtext
```

On Linux, install a full FFmpeg package with `drawtext` / libfreetype if possible.

The app uses your **system** FFmpeg, not MoviePy’s bundled copy.

### Python

Python **3.10+** and [uv](https://github.com/astral-sh/uv):

```bash
uv sync
uv run go-out --help
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ACOUSTID_API_KEY` | With `--identify` (default) | Key from [acoustid.org](https://acoustid.org/new-application) |
| `FFMPEG_BINARY` | No | Path to `ffmpeg` |
| `FFPROBE_BINARY` | No | Path to `ffprobe` (defaults to sibling of `FFMPEG_BINARY`) |

Export in your shell (the app does **not** read `.env` files):

```bash
export ACOUSTID_API_KEY=your_api_key_here
export FFMPEG_BINARY="$(brew --prefix ffmpeg-full)/bin/ffmpeg"
```

Or pass `--ffmpeg` on the command line.

## Usage

```bash
uv run go-out VIDEO SONGS_DIR [OPTIONS]
```

**Defaults:** AcoustID identification on, volume matching at **-12 LUFS**, video bitrate **`auto`** (~90% of input). Opt out with `--no-identify`, `--no-normalize`, `--target-lufs -16`, or `--bitrate off`.

| Option | Description |
|--------|-------------|
| `-o`, `--output PATH` | Output path (default: `{video_stem}_mixed.{ext}`) |
| `--trim-start` / `--trim-end` | Skip seconds from start or end of input |
| `--seed` | Reproducible song order |
| `--normalize` / `--no-normalize` | Match volume across songs (default: **on**) |
| `--normalize-mode` | `loudness` (default) or `peak` |
| `--target-lufs` | Loudness target (default: **-12**) |
| `--identify` / `--no-identify` | AcoustID labels (default: **on**) |
| `--allow-unmatched` | Include songs AcoustID could not match |
| `--preset`, `--crf` | x264 settings when not using hardware encode |
| `--bitrate` | `auto` (default), e.g. `8M` / `5000k`, or `off` |
| `--hw-encode` / `--no-hw-encode` | VideoToolbox on macOS (default: **on**) |
| `--scale` | Output height in pixels (e.g. `1080`) |
| `--ffmpeg` | Path to `ffmpeg` |
| `--prevent-sleep` / `--no-prevent-sleep` | macOS `caffeinate` during processing (default: **on**) |

**Examples**

```bash
uv run go-out my-video.mp4 ./songs
uv run go-out my-video.mp4 ./songs --seed 42 -o ~/Movies/output.mp4
uv run go-out my-video.mp4 ./songs --no-identify
uv run go-out my-video.mp4 ./songs --scale 1080 --bitrate 6M
```

### Probe a video

Inspect codec, resolution, duration, and bitrates (includes a suggested `--bitrate auto` value):

```bash
uv run go-out probe my-video.mp4
uv run go-out probe my-video.mp4 --json
```

### AcoustID

Matched **artist** and **title** are used in logs and on-screen labels. Unmatched files are **excluded** unless you pass `--allow-unmatched`. Results are cached in `.acoustid/` (gitignored), keyed by file size and mtime.

AcoustID is free for non-commercial use; commercial use requires a [license](https://acoustid.biz/).

## How it works

1. Read video duration (after trim).
2. Identify songs via AcoustID (unless `--no-identify`).
3. Shuffle and concatenate songs to match video length; normalize volume by default.
4. Export playlist audio, then FFmpeg encodes video with timed labels + H.264 + AAC.

Title rendering prefers **ASS subtitles**, then **`drawtext`**, then **PNG overlays** (slowest fallback).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No such filter: 'drawtext'` | Install `ffmpeg-full` and put it on `PATH`, or accept the PNG overlay fallback |
| `ffprobe` / `ffmpeg` not found | Install system FFmpeg; on macOS use `ffmpeg-full` |
| `ACOUSTID_API_KEY is not set` | Export the key or use `--no-identify` |
| `fpcalc` not found | `brew install chromaprint` or use `--no-identify` |

## Project layout

| Path | Description |
|------|-------------|
| `go_out/cli.py` | CLI (mix + `probe` subcommand) |
| `go_out/media.py` | ffprobe helpers and ffmpeg/ffprobe path resolution |
| `go_out/render.py` | FFmpeg encode and on-screen labels |
| `go_out/ui.py` | Rich terminal output |
| `go_out/acoustid.py` | AcoustID client and cache |
| `go_out/audio.py` | Volume normalization |
