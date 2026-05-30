import random
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer
from moviepy import AudioFileClip, VideoFileClip, afx, concatenate_audioclips

from acoustid_lookup import format_song_name, get_api_key, identify_songs
from video_render import render_video_with_overlays

app = typer.Typer()

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
        typer.echo(f"  + {label}")
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
    video: Path = typer.Argument(..., exists=True, help="Input video file"),
    songs: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Folder containing song .mp4 files",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output video path"
    ),
    seed: int | None = typer.Option(
        None, help="Random seed for reproducible song order"
    ),
    normalize: bool = typer.Option(
        False,
        "--normalize/--no-normalize",
        help="Peak-normalise each song so the loudest sample is at 0 dB",
    ),
    identify: bool = typer.Option(
        True,
        "--identify/--no-identify",
        help="Identify songs via AcoustID (uses ACOUSTID_API_KEY and .acoustid cache)",
    ),
    preset: str = typer.Option(
        "veryfast",
        help=f"x264 preset when not using hardware encode ({', '.join(ENCODE_PRESETS)})",
    ),
    crf: int = typer.Option(
        20,
        min=0,
        max=51,
        help="x264 quality (lower = better, slower). Ignored with --hw-encode.",
    ),
    hw_encode: bool | None = typer.Option(
        None,
        "--hw-encode/--no-hw-encode",
        help="Hardware H.264 via VideoToolbox (default: on for macOS, off otherwise)",
    ),
):
    if seed is not None:
        random.seed(seed)

    if preset not in ENCODE_PRESETS:
        raise typer.BadParameter(f"preset must be one of: {', '.join(ENCODE_PRESETS)}")

    song_files = sorted(songs.glob("*.mp4"))
    if not song_files:
        raise typer.BadParameter(f"No .mp4 files found in {songs}")

    song_names: dict[Path, str] = {path: path.stem for path in song_files}
    if identify:
        api_key = get_api_key()
        typer.echo("Identifying songs (cached in .acoustid/)...")
        matches = identify_songs(song_files, api_key)
        for path, match in matches.items():
            song_names[path] = format_song_name(match, path)
            typer.echo(f"  {path.name} → {song_names[path]}")

    output_path = output or video.with_name(f"{video.stem}_mixed{video.suffix}")

    typer.echo(f"Loading video: {video}")
    with VideoFileClip(str(video)) as video_clip:
        target_duration = video_clip.duration

    typer.echo(f"Video duration: {target_duration:.2f}s")
    typer.echo(f"Found {len(song_files)} songs, randomising order...")

    playlist, source_clips, segments = build_playlist(
        song_files,
        target_duration,
        normalize=normalize,
        song_names=song_names,
    )
    tmp_audio: Path | None = None
    use_hw = hw_encode if hw_encode is not None else sys.platform == "darwin"

    try:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp_audio = Path(tmp.name)

        typer.echo("Writing playlist audio...")
        playlist.write_audiofile(str(tmp_audio), codec="aac", logger="bar")

        encoder = "VideoToolbox" if use_hw else f"x264/{preset}"
        typer.echo(f"Rendering {output_path} ({encoder})...")
        render_video_with_overlays(
            video,
            tmp_audio,
            [(s.label, s.duration) for s in segments],
            output_path,
            preset=preset,
            crf=crf,
            hw_encode=hw_encode,
        )
    finally:
        playlist.close()
        for clip in source_clips:
            clip.close()
        if tmp_audio is not None and tmp_audio.exists():
            tmp_audio.unlink()

    typer.echo("Done!")


if __name__ == "__main__":
    app()
