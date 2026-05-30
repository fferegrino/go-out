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
| `FFMPEG_BINARY` | No | Path to `ffmpeg` (e.g. Homebrew `ffmpeg-full`; see below) |
| `FFPROBE_BINARY` | No | Path to `ffprobe` (defaults to `ffprobe` beside `FFMPEG_BINARY`) |

Export in your shell before running (the app does **not** read `.env` files):

```bash
export ACOUSTID_API_KEY=your_api_key_here
export FFMPEG_BINARY="$(brew --prefix ffmpeg-full)/bin/ffmpeg"
```

Or pass `--ffmpeg` on the command line:

```bash
uv run python main.py video.mp4 ./songs \
  --ffmpeg /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg
```

`ffprobe` is picked up automatically from the same directory unless you set `FFPROBE_BINARY`.

## AcoustID (song identification)

By default, each `.mp4` in the songs folder is identified via the [AcoustID](https://acoustid.org/) API (**`--identify` is on by default**). Matched **artist** and **title** are used in the log, on-screen labels, and playlist output. **Unmatched files are excluded** from the playlist unless you pass `--allow-unmatched`.

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

A basic run uses these **defaults** (no flags needed):

| Setting | Default |
|---------|---------|
| Song identification | **on** (`--identify`) — AcoustID artist/title labels |
| Volume matching | **on** (`--normalize`) at **-12 LUFS** |
| Video bitrate | **`auto`** — ~90% of the input video stream |

To opt out: `--no-identify`, `--no-normalize`, `--target-lufs -16`, or `--bitrate off` (quality-based encode, often larger files).

**Arguments**

- `VIDEO` — Input video file
- `SONGS_DIR` — Folder of song `.mp4` files (audio is extracted from these)

**Options**

| Option | Description |
|--------|-------------|
| `-o`, `--output PATH` | Output path (default: `{video_stem}_mixed.{ext}` beside the input) |
| `--trim-start SECS` | Skip this many seconds from the start of the input video (default: `0`) |
| `--trim-end SECS` | Skip this many seconds from the end of the input video (default: `0`) |
| `--seed INTEGER` | Random seed for the same song order on every run |
| `--normalize` / `--no-normalize` | Match volume across songs (default: **on**) |
| `--normalize-mode` | `loudness` (LUFS, recommended) or `peak` |
| `--target-lufs` | Target loudness in LUFS for loudness mode (default: **-12**) |
| `--identify` / `--no-identify` | AcoustID names for labels and logs (default: **on**) |
| `--allow-unmatched` | Include songs AcoustID could not match (default: **excluded** when identifying) |
| `--preset TEXT` | x264 preset when not using hardware encode: `ultrafast`, `veryfast`, `fast`, `medium`, `slow` (default: `veryfast`) |
| `--crf INTEGER` | x264 quality 0–51; lower is better (default: `20`). Ignored with `--hw-encode` or `--bitrate` (except `off`). |
| `--bitrate TEXT` | Target **video** bitrate: `auto` (default), e.g. `8M` / `5000k`, or `off` for quality-based encoding |
| `--hw-encode` / `--no-hw-encode` | H.264 via VideoToolbox (default: **on** on macOS, **off** elsewhere) |
| `--scale INTEGER` | Scale output to this height in pixels (e.g. `1080` for 4K sources) |
| `--ffmpeg PATH` | Path to `ffmpeg` (alternative to `FFMPEG_BINARY`) |
| `--prevent-sleep` / `--no-prevent-sleep` | Keep macOS awake during processing via `caffeinate` (default: **on** on macOS) |

**Examples**

```bash
# Basic run (identify + normalize @ -12 LUFS + --bitrate auto)
uv run python main.py my-video.mp4 ./songs

# Same playlist every time, custom output path
uv run python main.py my-video.mp4 ./songs --seed 42 -o ~/Movies/output.mp4

# Drop 5s from the start and 10s from the end
uv run python main.py my-video.mp4 ./songs --trim-start 5 --trim-end 10

# Skip volume matching or use a quieter streaming target
uv run python main.py my-video.mp4 ./songs --no-normalize
uv run python main.py my-video.mp4 ./songs --target-lufs -16

# Stricter peak matching (less even perceived loudness)
uv run python main.py my-video.mp4 ./songs --normalize --normalize-mode peak

# Fastest software encode (Linux or without VideoToolbox)
uv run python main.py my-video.mp4 ./songs --no-hw-encode --preset ultrafast --crf 23

# Quality-based video encode (no bitrate cap; often larger than input)
uv run python main.py my-video.mp4 ./songs --bitrate off

# Cap output size explicitly (good for 1080p; ~600 MB video per 10 minutes at 8M)
uv run python main.py my-video.mp4 ./songs --bitrate 8M

# Smaller 4K output: scale down and cap bitrate
uv run python main.py my-video.mp4 ./songs --scale 1080 --bitrate 6M
```

### Volume matching

Volume matching is **on by default** (`--normalize`). Songs from different sources often differ in loudness; normalization levels them before concatenation:

| Mode | Flag | What it does |
|------|------|----------------|
| **Loudness** (default) | `--normalize` | Matches **perceived** loudness to `--target-lufs` (default **-12 LUFS**) |
| **Peak** | `--normalize --normalize-mode peak` | Scales each track so its loudest sample hits 0 dB; quick but uneven across genres |

Use **`--no-normalize`** to skip volume matching. **-16 LUFS** is a common streaming target if you want something quieter: `--target-lufs -16`.

Loudness mode uses [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) (EBU R128-style integrated loudness). Each full track is measured before trimming, so the gain is based on the whole song.

## Rendering and speed

1. **Playlist audio** — MoviePy concatenates and normalises (by default) the shuffled songs to match the video length.
2. **Final video** — One FFmpeg pass muxes that audio with the video and burns in timed titles.

Title rendering picks the best method your FFmpeg supports:

| Method | When | Notes |
|--------|------|--------|
| **ASS subtitles** | Full FFmpeg build with `libass` (e.g. Homebrew `ffmpeg-full`) | Fastest for many tracks; preferred when available |
| **`drawtext`** | Full FFmpeg build without `libass` | One filter per segment |
| **PNG + `overlay`** | Neither filter available (e.g. Homebrew `ffmpeg` formula) | Labels rendered with Pillow; slowest |

On macOS, **VideoToolbox** (`--hw-encode`, default) is usually much faster than software x264. For software encoding, prefer `--preset veryfast` or `ultrafast`; lower `--crf` improves quality but takes longer.

Re-encoding is required to embed titles; the original video stream cannot be copied unchanged.

### Output file size and `--bitrate`

By default, **`--bitrate auto`** probes the input and targets ~**90%** of its video stream bitrate—keeping output size close to the source. This overrides quality-based encoding (`-q:v` / `--crf`).

Use an explicit cap or disable bitrate targeting:

| Value | Meaning |
|-------|---------|
| `auto` | **Default.** Probe the input video bitrate and target **90%** of it |
| `8M` | ~8 megabits per second (≈ 600 MB video per 10 minutes) |
| `5000k` | ~5 megabits per second (≈ 375 MB video per 10 minutes) |
| `off` | Quality-based encode (VideoToolbox / CRF); output can be **much larger** than the input, especially from HEVC sources |

**Notes:**

- `--bitrate` overrides quality settings (`-q:v` / `--crf`) for the video stream.
- Audio is separate (playlist AAC); total file size ≈ video bitrate + audio + container overhead.
- Lower bitrate → smaller file, more compression artifacts (especially around burned-in titles).
- Encode time stays about the same; bitrate mainly affects size and quality, not speed.
- H.264 at the same bitrate as HEVC may look slightly softer; bump `--bitrate` if needed.

Check an input file’s bitrate with the built-in probe command:

```bash
uv run python main.py probe INPUT.mp4
uv run python main.py probe INPUT.mp4 --json
```

Or run `probe.py` directly:

```bash
uv run python probe.py INPUT.mp4
```

The probe output includes a **Suggested --bitrate auto** value you can use when mixing.

### Prevent sleep (macOS)

Long encodes can take a while. On macOS, **sleep prevention is on by default** using the built-in `caffeinate` command for the whole run (identify, audio export, and render). Disable with `--no-prevent-sleep`.

You can also run `caffeinate` yourself around any command:

```bash
caffeinate -dims uv run python main.py my-video.mp4 ./songs
```

## How it works

1. Read the input video duration (after any `--trim-start` / `--trim-end`).
2. Identify each song via AcoustID (unless `--no-identify`) and cache in `.acoustid/`.
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

## Probe a video

Inspect codec, resolution, duration, and bitrates before mixing:

```bash
uv run python main.py probe my-video.mp4
uv run python main.py probe my-video.mp4 --json
```

Use the same `--ffmpeg` / `FFMPEG_BINARY` settings as the mix command. JSON output is useful for scripts.

## Project layout

| Path | Description |
|------|-------------|
| `main.py` | CLI entry point (mix + `probe` subcommand) |
| `probe.py` | Standalone probe CLI |
| `cli_ui.py` | Rich terminal UI (tables, progress, panels) |
| `ffmpeg_binaries.py` | Resolve `ffmpeg` / `ffprobe` paths |
| `media_probe.py` | ffprobe helpers (`VideoProbe`, bitrate formatting) |
| `video_render.py` | FFmpeg encode, ASS / drawtext / PNG overlay |
| `acoustid_lookup.py` | AcoustID client and `.acoustid` cache |
| `.acoustid/` | Cached identification results (gitignored) |
