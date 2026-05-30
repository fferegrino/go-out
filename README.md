# go-out

Build a video with a randomised soundtrack: songs from a folder are shuffled, concatenated to match the video length, and merged with the original video. The current song title is burned into the top-left corner and updates as each track plays.

## Requirements

### System

| Tool | Purpose |
|------|---------|
| [FFmpeg](https://ffmpeg.org/) | Used by MoviePy for audio/video processing and for the final merge |
| [Chromaprint](https://acoustid.org/chromaprint) (`fpcalc`) | Required for song identification via AcoustID |

Install on macOS with Homebrew:

```bash
brew install ffmpeg chromaprint
```

On other platforms, install FFmpeg and the Chromaprint package that provides the `fpcalc` command (must be on your `PATH`).

### Python

- Python **3.10+**
- Dependencies are managed with [uv](https://github.com/astral-sh/uv) (see `pyproject.toml`)

```bash
uv sync
```

## AcoustID (song identification)

By default, each `.mp4` in the songs folder is identified via the [AcoustID](https://acoustid.org/) API (artist and title from MusicBrainz metadata). Identification is **on** unless you pass `--no-identify`.

### API key

1. Register an application at [acoustid.org/new-application](https://acoustid.org/new-application).
2. Export the key in your shell (the app reads the environment only; it does not load `.env` files):

```bash
export ACOUSTID_API_KEY=your_api_key_here
```

AcoustID is **free for non-commercial** use. Commercial use requires a license from [AcoustID OÜ](https://acoustid.biz/).

### Cache

Lookups are cached under `.acoustid/` so unchanged files are not sent to the API again. A cache entry is tied to the file’s size and modification time; if you replace or edit a song file, it will be looked up again.

This directory is gitignored. Delete `.acoustid/` to force a full refresh.

### When identification is skipped

Use `--no-identify` if you do not have an API key, `fpcalc`, or you only want filenames in the logs.

## Usage

```bash
uv run python main.py VIDEO SONGS_DIR [OPTIONS]
```

**Arguments**

- `VIDEO` — Input video file
- `SONGS_DIR` — Folder of song `.mp4` files (audio is taken from these files)

**Options**

| Option | Description |
|--------|-------------|
| `-o`, `--output PATH` | Output path (default: `{video_stem}_mixed.{ext}` next to the input) |
| `--seed INTEGER` | Random seed for the same song order on every run |
| `--normalize` / `--no-normalize` | Peak-normalise each song before concatenation (default: off) |
| `--identify` / `--no-identify` | AcoustID song names in the log (default: on) |

**Examples**

```bash
# Basic run (identifies songs, writes video_mixed.mp4)
uv run python main.py my-video.mp4 ./songs

# Reproducible playlist and custom output
uv run python main.py my-video.mp4 ./songs --seed 42 -o output.mp4

# Normalised audio, no AcoustID
uv run python main.py my-video.mp4 ./songs --normalize --no-identify
```

## How it works

1. Read the input video duration.
2. Optionally identify each song (AcoustID + `.acoustid` cache).
3. Shuffle songs and append them until the total audio length matches the video (re-shuffle and continue if the folder is shorter than the video).
4. Trim the last song if needed.
5. Render the final file with the playlist audio and a top-left title overlay (white text, dark semi-transparent background). Video is re-encoded with H.264 (`crf 18`) so the text is part of the picture.

## Project layout

| Path | Description |
|------|-------------|
| `main.py` | CLI entry point |
| `acoustid_lookup.py` | AcoustID client and `.acoustid` cache |
| `.acoustid/` | Cached identification results (not committed) |
