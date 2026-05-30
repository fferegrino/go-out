import random
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer
from moviepy import AudioFileClip, VideoFileClip, afx, concatenate_audioclips

from acoustid_lookup import SongMatch, format_song_name, get_api_key, identify_songs
from cli_ui import (
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
from video_render import render_video_with_overlays, set_ffmpeg_binaries

app = typer.Typer(
    name="go-out",
    help="Mix a randomised soundtrack into a video with on-screen track titles.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)

ENCODE_PRESETS = ("ultrafast", "veryfast", "fast", "medium", "slow")


@dataclass(frozen=True)
class PlaylistSegment:
    label: str
    duration: float


def build_playlist(
    song_files: list[Path],
    target_duration: float,
    *,
    normalize: bool = False,
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
            clip = clip.with_effects([afx.AudioNormalize()])

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
    seed: int | None = typer.Option(
        None,
        help="Random seed for reproducible song order",
        rich_help_panel="Playlist",
    ),
    normalize: bool = typer.Option(
        False,
        "--normalize/--no-normalize",
        help="Peak-normalise each song so the loudest sample is at 0 dB",
        rich_help_panel="Playlist",
    ),
    identify: bool = typer.Option(
        True,
        "--identify/--no-identify",
        help="Identify songs via AcoustID (uses ACOUSTID_API_KEY)",
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
        help="x264 quality; lower is better. Ignored with --hw-encode.",
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
) -> None:
    """Build a video with a shuffled soundtrack and timed on-screen song titles."""
    if ffmpeg_bin is not None and not ffmpeg_bin.is_file():
        raise typer.BadParameter(f"ffmpeg binary not found: {ffmpeg_bin}")

    set_ffmpeg_binaries(ffmpeg=ffmpeg_bin)
    if seed is not None:
        random.seed(seed)

    if preset not in ENCODE_PRESETS:
        raise typer.BadParameter(f"preset must be one of: {', '.join(ENCODE_PRESETS)}")

    song_files = sorted(songs.glob("*.mp4"))
    if not song_files:
        raise typer.BadParameter(f"No .mp4 files found in {songs}")

    print_banner()
    console.print()

    song_names: dict[Path, str] = {path: path.stem for path in song_files}
    if identify:
        api_key = get_api_key()
        with task("Identifying songs (AcoustID)…"):
            matches = identify_songs(song_files, api_key)
        id_rows: list[tuple[str, str, SongMatch]] = []
        for path, match in matches.items():
            song_names[path] = format_song_name(match, path)
            id_rows.append((path.name, song_names[path], match))
        print_identification_results(id_rows)
        console.print()

    output_path = output or video.with_name(f"{video.stem}_mixed{video.suffix}")
    use_hw = hw_encode if hw_encode is not None else sys.platform == "darwin"
    encoder = "VideoToolbox" if use_hw else f"x264 · {preset} · crf {crf}"
    labels = label_mode_name()
    note_png_fallback()

    with task("Reading video…"):
        with VideoFileClip(str(video)) as video_clip:
            target_duration = video_clip.duration

    print_run_summary(
        video=video,
        songs_dir=songs,
        output=output_path,
        video_duration=target_duration,
        song_count=len(song_files),
        seed=seed,
        normalize=normalize,
        identify=identify,
        encoder=encoder,
        label_mode=labels,
    )
    console.print()

    with task("Building playlist…"):
        playlist, source_clips, segments = build_playlist(
            song_files,
            target_duration,
            normalize=normalize,
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
    )


if __name__ == "__main__":
    app()
