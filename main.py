import random
import tempfile
from pathlib import Path

import typer
from moviepy import AudioFileClip, VideoFileClip, afx, concatenate_audioclips
from moviepy.config import FFMPEG_BINARY
from moviepy.tools import ffmpeg_escape_filename, subprocess_call

from acoustid_lookup import format_song_name, get_api_key, identify_songs

app = typer.Typer()


def build_playlist(
    song_files: list[Path],
    target_duration: float,
    *,
    normalize: bool = False,
    song_names: dict[Path, str] | None = None,
) -> tuple[AudioFileClip, list[AudioFileClip]]:
    """Shuffle songs and collect clips whose total duration matches the target."""
    playlist = song_files.copy()
    random.shuffle(playlist)

    clips: list[AudioFileClip] = []
    remaining = target_duration
    index = 0

    while remaining > 0.01:
        if index > 0 and index % len(playlist) == 0:
            random.shuffle(playlist)

        song_path = playlist[index % len(playlist)]
        clip = AudioFileClip(str(song_path))
        index += 1
        if song_names is not None:
            typer.echo(f"  + {song_names.get(song_path, song_path.name)}")
        if normalize:
            clip = clip.with_effects([afx.AudioNormalize()])

        if clip.duration <= remaining:
            clips.append(clip)
            remaining -= clip.duration
        else:
            clips.append(clip.subclipped(0, remaining))
            remaining = 0

    return concatenate_audioclips(clips), clips


def merge_video_audio(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """Merge video and audio, copying the video stream without re-encoding."""
    cmd = [
        FFMPEG_BINARY,
        "-y",
        "-i",
        ffmpeg_escape_filename(str(video_path)),
        "-i",
        ffmpeg_escape_filename(str(audio_path)),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        ffmpeg_escape_filename(str(output_path)),
    ]
    subprocess_call(cmd, logger="bar")


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
):
    if seed is not None:
        random.seed(seed)

    song_files = sorted(songs.glob("*.mp4"))
    if not song_files:
        raise typer.BadParameter(f"No .mp4 files found in {songs}")

    song_names: dict[Path, str] = {path: path.name for path in song_files}
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

    playlist, source_clips = build_playlist(
        song_files,
        target_duration,
        normalize=normalize,
        song_names=song_names if identify else None,
    )
    tmp_audio: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp_audio = Path(tmp.name)

        typer.echo("Writing concatenated audio...")
        playlist.write_audiofile(str(tmp_audio), codec="aac", logger="bar")

        typer.echo(f"Merging into {output_path} (video stream copied, no re-encode)...")
        merge_video_audio(video, tmp_audio, output_path)
    finally:
        playlist.close()
        for clip in source_clips:
            clip.close()
        if tmp_audio is not None and tmp_audio.exists():
            tmp_audio.unlink()

    typer.echo("Done!")


if __name__ == "__main__":
    app()
