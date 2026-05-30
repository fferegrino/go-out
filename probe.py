"""Probe media files with ffprobe."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer

from cli_ui import console, print_probe_results
from media_probe import VideoProbe, probe_video
from video_render import set_ffmpeg_binaries

app = typer.Typer(
    name="probe",
    help="Inspect a video file with ffprobe (codec, bitrate, duration, etc.).",
    rich_markup_mode="rich",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)


def _probe_to_json(probe: VideoProbe) -> dict:
    return {
        "path": str(probe.path),
        "codec": probe.codec,
        "width": probe.width,
        "height": probe.height,
        "duration": probe.duration,
        "file_size": probe.file_size,
        "video_bitrate_bps": probe.video_bitrate_bps,
        "format_bitrate_bps": probe.format_bitrate_bps,
        "estimated_video_bitrate_bps": probe.estimated_video_bitrate_bps,
        "audio_codec": probe.audio_codec,
        "audio_bitrate_bps": probe.audio_bitrate_bps,
        "suggested_auto_bitrate": probe.suggested_auto_bitrate,
    }


@app.command()
def main(
    video: Path = typer.Argument(
        ...,
        exists=True,
        help="Video file to inspect",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print probe results as JSON",
    ),
    ffmpeg_bin: Path | None = typer.Option(
        None,
        "--ffmpeg",
        help="Path to ffmpeg binary (ffprobe is resolved beside it)",
    ),
) -> None:
    """Show codec, resolution, duration, and bitrate info for a video file."""
    if ffmpeg_bin is not None and not ffmpeg_bin.is_file():
        raise typer.BadParameter(f"ffmpeg binary not found: {ffmpeg_bin}")

    set_ffmpeg_binaries(ffmpeg=ffmpeg_bin)

    try:
        probe = probe_video(video)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc

    if json_output:
        console.print_json(json.dumps(_probe_to_json(probe)))
    else:
        print_probe_results(probe)


if __name__ == "__main__":
    app()
