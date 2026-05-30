import random
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import typer
from moviepy import AudioFileClip, VideoFileClip, concatenate_audioclips

from go_out.acoustid import SongMatch, format_song_name, get_api_key, identify_songs
from go_out.audio import DEFAULT_TARGET_LUFS, NormalizeMode, normalize_clip
from go_out.media import resolve_video_bitrate
from go_out.render import render_video_with_overlays, set_ffmpeg_binaries
from go_out.sleep import default_prevent_sleep, prevent_system_sleep
from go_out.ui import (
    console,
    label_mode_name,
    note_png_fallback,
    print_banner,
    print_done,
    print_identification_results,
    print_playlist,
    print_run_summary,
    task,
)

app = typer.Typer(
    name="go-out",
    help="Mix a randomised soundtrack into a video with on-screen track titles.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)

ENCODE_PRESETS = ("ultrafast", "veryfast", "fast", "medium", "slow")
NORMALIZE_MODES = ("loudness", "peak")


@dataclass(frozen=True)
class PlaylistSegment:
    label: str
    duration: float


def build_playlist(
    song_files: list[Path],
    target_duration: float,
    *,
    normalize: bool = False,
    normalize_mode: NormalizeMode = "loudness",
    target_lufs: float = DEFAULT_TARGET_LUFS,
    song_names: dict[Path, str],
) -> tuple[AudioFileClip, list[AudioFileClip], list[PlaylistSegment]]:
    """Shuffle songs and collect clips whose total duration matches the target."""
    playlist = song_files.copy()
    random.shuffle(playlist)

    clips: list[AudioFileClip] = []
    segments: list[PlaylistSegment] = []
    remaining = target_duration
    index = 0

    while remaining > 0.01:
        if index > 0 and index % len(playlist) == 0:
            random.shuffle(playlist)

        song_path = playlist[index % len(playlist)]
        clip = AudioFileClip(str(song_path))
        index += 1
        label = song_names.get(song_path, song_path.name)
        if normalize:
            clip = normalize_clip(
                clip, mode=normalize_mode, target_lufs=target_lufs
            )

        if clip.duration <= remaining:
            clips.append(clip)
            remaining -= clip.duration
        else:
            clip = clip.subclipped(0, remaining)
            clips.append(clip)
            remaining = 0

        segments.append(PlaylistSegment(label=label, duration=clip.duration))

    return concatenate_audioclips(clips), clips, segments


@app.command()
def main(
    video: Path = typer.Argument(
        ...,
        exists=True,
        help="Input video file",
        rich_help_panel="Inputs",
    ),
    songs: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Folder of song .mp4 files",
        rich_help_panel="Inputs",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output video path",
        rich_help_panel="Output",
    ),
    trim_start: float = typer.Option(
        0.0,
        "--trim-start",
        min=0.0,
        help="Skip this many seconds from the start of the input video",
        rich_help_panel="Inputs",
    ),
    trim_end: float = typer.Option(
        0.0,
        "--trim-end",
        min=0.0,
        help="Skip this many seconds from the end of the input video",
        rich_help_panel="Inputs",
    ),
    seed: int | None = typer.Option(
        None,
        help="Random seed for reproducible song order",
        rich_help_panel="Playlist",
    ),
    normalize: bool = typer.Option(
        True,
        "--normalize/--no-normalize",
        help="Match volume across songs (default method: loudness / LUFS)",
        rich_help_panel="Playlist",
    ),
    normalize_mode: str = typer.Option(
        "loudness",
        "--normalize-mode",
        help="Volume matching: loudness (LUFS, recommended) or peak",
        rich_help_panel="Playlist",
    ),
    target_lufs: float = typer.Option(
        DEFAULT_TARGET_LUFS,
        "--target-lufs",
        help="Target integrated loudness in LUFS when using loudness mode (default: -12)",
        rich_help_panel="Playlist",
    ),
    identify: bool = typer.Option(
        True,
        "--identify/--no-identify",
        help="Identify songs via AcoustID (uses ACOUSTID_API_KEY)",
        rich_help_panel="Playlist",
    ),
    allow_unmatched: bool = typer.Option(
        False,
        "--allow-unmatched",
        help="Include songs AcoustID could not match (default: exclude them)",
        rich_help_panel="Playlist",
    ),
    preset: str = typer.Option(
        "veryfast",
        help=f"x264 preset ({', '.join(ENCODE_PRESETS)})",
        rich_help_panel="Encoding",
    ),
    crf: int = typer.Option(
        20,
        min=0,
        max=51,
        help="x264 quality; lower is better. Ignored with --hw-encode or --bitrate.",
        rich_help_panel="Encoding",
    ),
    hw_encode: bool | None = typer.Option(
        None,
        "--hw-encode/--no-hw-encode",
        help="Hardware H.264 via VideoToolbox (default: on on macOS)",
        rich_help_panel="Encoding",
    ),
    ffmpeg_bin: Path | None = typer.Option(
        None,
        "--ffmpeg",
        help="Path to ffmpeg binary (or set FFMPEG_BINARY)",
        rich_help_panel="Encoding",
    ),
    scale: int | None = typer.Option(
        None,
        "--scale",
        min=144,
        help="Scale output to this height in pixels (e.g. 1080 for 4K sources)",
        rich_help_panel="Encoding",
    ),
    bitrate: str = typer.Option(
        "auto",
        "--bitrate",
        help="Video bitrate (e.g. 8M, 5000k), auto (~90% of input), or off for quality-based encode",
        rich_help_panel="Encoding",
    ),
    prevent_sleep: bool = typer.Option(
        default_prevent_sleep(),
        "--prevent-sleep/--no-prevent-sleep",
        help="Keep the system awake while processing (macOS: caffeinate)",
        rich_help_panel="Processing",
    ),
) -> None:
    """Build a video with a shuffled soundtrack and timed on-screen song titles."""
    if ffmpeg_bin is not None and not ffmpeg_bin.is_file():
        raise typer.BadParameter(f"ffmpeg binary not found: {ffmpeg_bin}")

    set_ffmpeg_binaries(ffmpeg=ffmpeg_bin)
    if seed is not None:
        random.seed(seed)

    if preset not in ENCODE_PRESETS:
        raise typer.BadParameter(f"preset must be one of: {', '.join(ENCODE_PRESETS)}")

    if normalize_mode not in NORMALIZE_MODES:
        raise typer.BadParameter(
            f"normalize-mode must be one of: {', '.join(NORMALIZE_MODES)}"
        )

    song_files = sorted(songs.glob("*.mp4"))
    if not song_files:
        raise typer.BadParameter(f"No .mp4 files found in {songs}")

    print_banner()
    console.print()

    with prevent_system_sleep(prevent_sleep):
        _run(
            video=video,
            songs=songs,
            song_files=song_files,
            output_path=output or video.with_name(f"{video.stem}_mixed{video.suffix}"),
            seed=seed,
            normalize=normalize,
            normalize_mode=normalize_mode,  # type: ignore[arg-type]
            target_lufs=target_lufs,
            identify=identify,
            allow_unmatched=allow_unmatched,
            preset=preset,
            crf=crf,
            hw_encode=hw_encode,
            scale=scale,
            bitrate=bitrate,
            trim_start=trim_start,
            trim_end=trim_end,
            prevent_sleep=prevent_sleep,
        )


def _encoder_label(
    *,
    use_hw: bool,
    preset: str,
    crf: int,
    video_bitrate: str | None,
) -> str:
    if use_hw:
        label = "VideoToolbox"
    else:
        label = f"x264 · {preset}"
        if video_bitrate is None:
            label += f" · crf {crf}"
    if video_bitrate is not None:
        label += f" · {video_bitrate}"
    return label


def _run(
    *,
    video: Path,
    songs: Path,
    song_files: list[Path],
    output_path: Path,
    seed: int | None,
    normalize: bool,
    normalize_mode: NormalizeMode,
    target_lufs: float,
    identify: bool,
    allow_unmatched: bool,
    preset: str,
    crf: int,
    hw_encode: bool | None,
    scale: int | None,
    bitrate: str,
    trim_start: float,
    trim_end: float,
    prevent_sleep: bool,
) -> None:
    run_start = time.perf_counter()
    resolved_bitrate: str | None = None
    bitrate_display: str | None = None
    if bitrate.lower() != "off":
        try:
            resolved_bitrate = resolve_video_bitrate(video, bitrate)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if bitrate.lower() == "auto":
            bitrate_display = f"auto → {resolved_bitrate}"
        else:
            bitrate_display = resolved_bitrate

    song_names: dict[Path, str] = {path: path.stem for path in song_files}
    if identify:
        api_key = get_api_key()
        with task("Identifying songs (AcoustID)…"):
            matches = identify_songs(song_files, api_key)
        id_rows: list[tuple[str, str, SongMatch]] = []
        for path, match in matches.items():
            song_names[path] = format_song_name(match, path)
            id_rows.append((path.name, song_names[path], match))
        exclude_unmatched = not allow_unmatched
        print_identification_results(id_rows, exclude_unmatched=exclude_unmatched)
        console.print()

        if exclude_unmatched:
            matched_files = [path for path in song_files if matches[path].matched]
            skipped = len(song_files) - len(matched_files)
            if skipped:
                console.print(
                    f"[yellow]Excluded {skipped} unmatched "
                    f"{'file' if skipped == 1 else 'files'}[/yellow] "
                    f"([dim]use --allow-unmatched to include them[/dim])"
                )
                console.print()
            if not matched_files:
                raise typer.BadParameter(
                    "No songs matched AcoustID. Fix your library, clear .acoustid/, "
                    "or pass --allow-unmatched."
                )
            song_files = matched_files

    use_hw = hw_encode if hw_encode is not None else sys.platform == "darwin"
    encoder = _encoder_label(
        use_hw=use_hw,
        preset=preset,
        crf=crf,
        video_bitrate=bitrate_display or resolved_bitrate,
    )
    labels = label_mode_name()
    note_png_fallback()

    with task("Reading video…"):
        with VideoFileClip(str(video)) as video_clip:
            source_duration = video_clip.duration

    if trim_start + trim_end >= source_duration - 0.01:
        raise typer.BadParameter(
            f"--trim-start ({trim_start}s) + --trim-end ({trim_end}s) "
            f"removes the entire video ({source_duration:.1f}s)."
        )
    target_duration = source_duration - trim_start - trim_end
    render_trim_duration = target_duration if trim_start > 0 or trim_end > 0 else None

    print_run_summary(
        video=video,
        songs_dir=songs,
        output=output_path,
        video_duration=target_duration,
        source_duration=source_duration if trim_start > 0 or trim_end > 0 else None,
        trim_start=trim_start,
        trim_end=trim_end,
        song_count=len(song_files),
        seed=seed,
        normalize=normalize,
        normalize_mode=normalize_mode,
        target_lufs=target_lufs,
        identify=identify,
        encoder=encoder,
        label_mode=labels,
        scale=scale,
        video_bitrate=bitrate_display,
        prevent_sleep=prevent_sleep,
    )
    console.print()

    with task("Building playlist…"):
        playlist, source_clips, segments = build_playlist(
            song_files,
            target_duration,
            normalize=normalize,
            normalize_mode=normalize_mode,
            target_lufs=target_lufs,
            song_names=song_names,
        )

    segment_rows = [(s.label, s.duration) for s in segments]
    print_playlist(segment_rows)
    console.print()

    tmp_audio: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp_audio = Path(tmp.name)

        with task("Writing playlist audio…"):
            playlist.write_audiofile(str(tmp_audio), codec="aac", logger=None)

        with task(f"Rendering video ({encoder})…"):
            render_video_with_overlays(
                video,
                tmp_audio,
                segment_rows,
                output_path,
                preset=preset,
                crf=crf,
                hw_encode=hw_encode,
                scale_height=scale,
                video_bitrate=resolved_bitrate,
                trim_start=trim_start,
                trim_duration=render_trim_duration,
                quiet=True,
            )
    finally:
        playlist.close()
        for clip in source_clips:
            clip.close()
        if tmp_audio is not None and tmp_audio.exists():
            tmp_audio.unlink()

    print_done(
        output_path,
        segment_count=len(segments),
        encoder=encoder,
        label_mode=labels,
        elapsed=time.perf_counter() - run_start,
    )

