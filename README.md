# go-out

Build a video with a randomised soundtrack: songs from a folder are shuffled, concatenated to match the video length, and merged with the original video. The **current song title** is shown in the **top-left corner** and updates when each track starts.

## Requirements

### System

| Tool | Purpose |
|------|---------|
| [FFmpeg](https://ffmpeg.org/) (`ffmpeg`, `ffprobe`) | Audio playlist export, final encode, on-screen titles |
| [Chromaprint](https://acoustid.org/chromaprint) (`fpcalc`) | Fingerprinting for AcoustID (only when `--identify` is on) |

Install on macOS with Homebrew:

```bash
brew install ffmpeg-full chromaprint
```

Use **`ffmpeg-full`**, not the default `ffmpeg` formula. The standard Homebrew `ffmpeg` build is minimal and often omits filters such as `drawtext`. `ffmpeg-full` includes those libraries and is what this project is tested with on macOS.

`ffmpeg-full` is [keg-only](https://docs.brew.sh/FAQ#what-does-keg-only-mean). Put it on your `PATH` before other FFmpeg installs:

```bash
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
```

Add that line to your shell profile (`~/.zshrc`, etc.) if you use it often. Confirm the right binaries are used:

```bash
which ffmpeg ffprobe
ffmpeg -filters 2>&1 | grep drawtext
```

On Linux and other platforms, install a **full** FFmpeg package (with libfreetype / `drawtext` if possible) and ensure **`ffmpeg` and `ffprobe` are on your `PATH`**.

The app uses your **system** FFmpeg (not MoviePy’s bundled copy).

### Python

- Python **3.10+**
- Dependencies: [uv](https://github.com/astral-sh/uv) (see `pyproject.toml`)

```bash
uv sync
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ACOUSTID_API_KEY` | When using `--identify` (default) | API key from [acoustid.org](https://acoustid.org/new-application) |

Export in your shell before running (the app does **not** read `.env` files):

```bash
export ACOUSTID_API_KEY=your_api_key_here
```

## AcoustID (song identification)

By default, each `.mp4` in the songs folder is identified via the [AcoustID](https://acoustid.org/) API. Matched **artist** and **title** are used in the log, on-screen labels, and playlist output.

AcoustID is **free for non-commercial** use. Commercial use requires a license from [AcoustID OÜ](https://acoustid.biz/).

### Cache

Lookups are stored under `.acoustid/` (gitignored). Each entry is keyed to the file’s **size** and **modification time**; editing or replacing a file triggers a new lookup. Delete `.acoustid/` to refresh everything.

### Skip identification

Use `--no-identify` if you have no API key, no `fpcalc`, or you only want file stems as labels:

```bash
uv run python main.py my-video.mp4 ./songs --no-identify
```

## Usage

```bash
uv run python main.py VIDEO SONGS_DIR [OPTIONS]
```

**Arguments**

- `VIDEO` — Input video file
- `SONGS_DIR` — Folder of song `.mp4` files (audio is extracted from these)

**Options**

| Option | Description |
|--------|-------------|
| `-o`, `--output PATH` | Output path (default: `{video_stem}_mixed.{ext}` beside the input) |
| `--seed INTEGER` | Random seed for the same song order on every run |
| `--normalize` / `--no-normalize` | Peak-normalise each song before concatenation (default: off) |
| `--identify` / `--no-identify` | AcoustID names for labels and logs (default: on) |
| `--preset TEXT` | x264 preset when not using hardware encode: `ultrafast`, `veryfast`, `fast`, `medium`, `slow` (default: `veryfast`) |
| `--crf INTEGER` | x264 quality 0–51; lower is better (default: `20`). Ignored with `--hw-encode`. |
| `--hw-encode` / `--no-hw-encode` | H.264 via VideoToolbox (default: **on** on macOS, **off** elsewhere) |

**Examples**

```bash
# Basic run
uv run python main.py my-video.mp4 ./songs

# Same playlist every time, custom output path
uv run python main.py my-video.mp4 ./songs --seed 42 -o ~/Movies/output.mp4

# Louder-matched songs, file names only (no AcoustID)
uv run python main.py my-video.mp4 ./songs --normalize --no-identify

# Fastest software encode (Linux or without VideoToolbox)
uv run python main.py my-video.mp4 ./songs --no-hw-encode --preset ultrafast --crf 23
```

## Rendering and speed

1. **Playlist audio** — MoviePy concatenates (and optionally normalises) the shuffled songs to match the video length.
2. **Final video** — One FFmpeg pass muxes that audio with the video and burns in timed titles.

Title rendering picks the best method your FFmpeg supports:

| Method | When | Notes |
|--------|------|--------|
| **`drawtext`** | Full FFmpeg build (e.g. Homebrew `ffmpeg-full`) | Fastest; used automatically if available |
| **PNG + `overlay`** | `drawtext` missing (e.g. Homebrew `ffmpeg` formula) | Labels rendered with Pillow; message printed to stderr |

On macOS, **VideoToolbox** (`--hw-encode`, default) is usually much faster than software x264. For software encoding, prefer `--preset veryfast` or `ultrafast`; lower `--crf` improves quality but takes longer.

Re-encoding is required to embed titles; the original video stream cannot be copied unchanged.

## How it works

1. Read the input video duration.
2. Optionally identify each song (AcoustID + `.acoustid` cache).
3. Shuffle songs and append until audio length matches the video (re-shuffle and continue if the folder is shorter than the video).
4. Trim the last song if needed.
5. Write playlist audio to a temporary file.
6. FFmpeg encodes the output: timed top-left labels + H.264 (VideoToolbox or x264) + AAC audio.

## Troubleshooting

### `No such filter: 'drawtext'`

Your FFmpeg was built without `drawtext` (typical with Homebrew’s `ffmpeg` formula). Either:

- **Recommended on macOS:** install the full build and prefer it on `PATH`:

  ```bash
  brew install ffmpeg-full
  export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
  ffmpeg -filters 2>&1 | grep drawtext
  ```

- **Or** rely on the automatic **PNG overlay** fallback (no `drawtext` needed). You should see: `ffmpeg has no drawtext filter; rendering labels with PNG overlays.`

### `FileNotFoundError` for `ffprobe` under `imageio_ffprobe`

Install system tools and ensure they are on `PATH` (on macOS, use `ffmpeg-full` as above):

```bash
brew install ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
which ffmpeg ffprobe
```

### `ACOUSTID_API_KEY is not set`

Export the key (see [Environment variables](#environment-variables)) or run with `--no-identify`.

### `Chromaprint is required` / `fpcalc` not found

```bash
brew install chromaprint
```

Or use `--no-identify`.

## Project layout

| Path | Description |
|------|-------------|
| `main.py` | CLI entry point |
| `cli_ui.py` | Rich terminal UI (tables, progress, panels) |
| `video_render.py` | FFmpeg encode, `drawtext` / PNG overlay |
| `acoustid_lookup.py` | AcoustID client and `.acoustid` cache |
| `.acoustid/` | Cached identification results (gitignored) |
