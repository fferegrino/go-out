import random
from dataclasses import dataclass
from pathlib import Path

import typer
from moviepy import (
    AudioFileClip,
    CompositeVideoClip,
    TextClip,
    VideoFileClip,
    afx,
    concatenate_audioclips,
)

from acoustid_lookup import format_song_name, get_api_key, identify_songs

app = typer.Typer()


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


def render_video_with_overlays(
    video_path: Path,
    audio: AudioFileClip,
    segments: list[PlaylistSegment],
    output_path: Path,
) -> None:
    """Burn song titles into the video and attach the playlist audio."""
    video = VideoFileClip(str(video_path))
    text_clips: list[TextClip] = []
    final = None

    try:
        _, height = video.size
        font_size = max(24, height // 28)
        margin = max(12, height // 48)

        start = 0.0
        for segment in segments:
            text = TextClip(
                text=segment.label,
                font_size=font_size,
                color="white",
                stroke_color="black",
                stroke_width=2,
                bg_color=(0, 0, 0, 180),
                method="label",
            )
            text = (
                text.with_duration(segment.duration)
                .with_start(start)
                .with_position((margin, margin))
            )
            text_clips.append(text)
            start += segment.duration

        final = CompositeVideoClip([video, *text_clips], use_bgclip=True)
        final = final.with_duration(video.duration).with_audio(audio)
        final.write_videofile(
            str(output_path),
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            ffmpeg_params=["-crf", "18"],
            logger="bar",
        )
    finally:
        if final is not None:
            final.close()
        for text in text_clips:
            text.close()
        video.close()


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

    try:
        typer.echo(f"Rendering {output_path} with song titles...")
        render_video_with_overlays(video, playlist, segments, output_path)
    finally:
        playlist.close()
        for clip in source_clips:
            clip.close()

    typer.echo("Done!")


if __name__ == "__main__":
    app()
