"""Rich terminal UI for go-out."""

from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from go_out.acoustid import SongMatch
from go_out.audio import DEFAULT_TARGET_LUFS
from go_out.ffmpeg import ffprobe_binary
from go_out.media import VideoProbe, format_file_size, format_human_bitrate
from go_out.render import ffmpeg_binary, label_render_mode

console = Console()
err_console = Console(stderr=True)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def print_banner() -> None:
    console.print(
        Panel.fit(
            Text.from_markup(
                "[bold cyan]go-out[/]  "
                "Random soundtrack · on-screen track titles"
            ),
            border_style="cyan",
        )
    )


def print_run_summary(
    *,
    video: Path,
    songs_dir: Path,
    output: Path,
    video_duration: float,
    song_count: int,
    seed: int | None,
    normalize: bool,
    normalize_mode: str = "loudness",
    target_lufs: float = DEFAULT_TARGET_LUFS,
    identify: bool,
    encoder: str,
    label_mode: str,
    scale: int | None = None,
    video_bitrate: str | None = None,
    source_duration: float | None = None,
    trim_start: float = 0.0,
    trim_end: float = 0.0,
    prevent_sleep: bool = False,
) -> None:
    table = Table(
        title="Run",
        box=box.ROUNDED,
        show_header=False,
        padding=(0, 1),
    )
    table.add_column("Setting", style="dim", no_wrap=True)
    table.add_column("Value")

    table.add_row("Video", str(video))
    table.add_row("Songs", f"{songs_dir} [dim]({song_count} tracks)[/dim]")
    table.add_row("Output", str(output))
    if source_duration is not None:
        table.add_row("Source duration", format_duration(source_duration))
    table.add_row("Duration", format_duration(video_duration))
    if trim_start > 0 or trim_end > 0:
        parts: list[str] = []
        if trim_start > 0:
            parts.append(f"{format_duration(trim_start)} start")
        if trim_end > 0:
            parts.append(f"{format_duration(trim_end)} end")
        table.add_row("Trim", " · ".join(parts))
    table.add_row("FFmpeg", ffmpeg_binary())
    table.add_row("Encoder", encoder)
    table.add_row("Labels", label_mode)
    if video_bitrate is not None:
        table.add_row("Bitrate", video_bitrate)
    if scale is not None:
        table.add_row("Scale", f"{scale}p height")
    table.add_row("Identify", "on" if identify else "off")
    if normalize:
        if normalize_mode == "loudness":
            table.add_row("Normalize", f"loudness · {target_lufs:.0f} LUFS")
        else:
            table.add_row("Normalize", "peak")
    else:
        table.add_row("Normalize", "off")
    if prevent_sleep and sys.platform == "darwin":
        table.add_row("Sleep", "[dim]prevented (caffeinate)[/dim]")
    if seed is not None:
        table.add_row("Seed", str(seed))

    console.print(table)


def print_probe_results(probe: VideoProbe) -> None:
    table = Table(
        title="Media probe",
        box=box.ROUNDED,
        show_header=False,
        padding=(0, 1),
    )
    table.add_column("Field", style="dim", no_wrap=True)
    table.add_column("Value")

    table.add_row("File", str(probe.path))
    table.add_row("Size", format_file_size(probe.file_size))
    table.add_row("Duration", format_duration(probe.duration))
    table.add_row("Resolution", probe.resolution)
    table.add_row("Video codec", probe.codec)
    table.add_row(
        "Video bitrate",
        format_human_bitrate(probe.video_bitrate_bps),
    )
    table.add_row(
        "Estimated video bitrate",
        format_human_bitrate(probe.estimated_video_bitrate_bps),
    )
    table.add_row(
        "Container bitrate",
        format_human_bitrate(probe.format_bitrate_bps),
    )
    if probe.audio_codec:
        table.add_row("Audio codec", probe.audio_codec)
        table.add_row(
            "Audio bitrate",
            format_human_bitrate(probe.audio_bitrate_bps),
        )
    table.add_row("FFprobe", ffprobe_binary())
    if probe.suggested_auto_bitrate:
        table.add_row(
            "Suggested --bitrate auto",
            f"[cyan]{probe.suggested_auto_bitrate}[/cyan]",
        )

    console.print(table)


def print_identification_results(
    rows: list[tuple[str, str, SongMatch]],
    *,
    exclude_unmatched: bool = False,
) -> None:
    table = Table(
        title="AcoustID",
        caption=(
            "Unmatched files are excluded from the playlist."
            if exclude_unmatched
            else "Cached in .acoustid/"
        ),
        box=box.SIMPLE_HEAD,
    )
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Detected title")
    table.add_column("Match", justify="right", width=8)
    table.add_column("Status", justify="center", width=10)

    for filename, title, match in rows:
        if match.matched:
            score = f"[green]{match.score:.0%}[/]"
            status = "[green]included[/green]"
            display_title = title
        else:
            score = "[red]—[/red]" if match.score == 0 else f"[yellow]{match.score:.0%}[/]"
            status = (
                "[red]excluded[/red]"
                if exclude_unmatched
                else "[yellow]unmatched[/yellow]"
            )
            display_title = f"[dim]{filename}[/dim]"

        table.add_row(filename, display_title, score, status)

    console.print(table)


def print_playlist(segments: list[tuple[str, float]]) -> None:
    table = Table(title="Playlist", box=box.SIMPLE_HEAD)
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Track")
    table.add_column("Length", justify="right", width=8)
    table.add_column("Starts", justify="right", width=8)

    start = 0.0
    for index, (label, duration) in enumerate(segments, start=1):
        table.add_row(
            str(index),
            label,
            format_duration(duration),
            format_duration(start),
        )
        start += duration

    table.add_row(
        "",
        "[dim]Total[/dim]",
        f"[bold]{format_duration(start)}[/bold]",
        "",
    )
    console.print(table)


def print_done(
    output: Path,
    *,
    segment_count: int,
    encoder: str,
    label_mode: str,
    elapsed: float,
) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold green]✓[/bold green]  [bold]{output}[/bold]\n\n"
            f"[dim]{segment_count} segments · {encoder} · {label_mode} · "
            f"elapsed {format_duration(elapsed)}[/dim]",
            title="Finished",
            border_style="green",
            padding=(1, 2),
        )
    )


def label_mode_name() -> str:
    return {
        "ass": "ASS subtitles",
        "drawtext": "drawtext",
        "png": "PNG overlay",
    }[label_render_mode()]


def note_png_fallback() -> None:
    if label_render_mode() == "png":
        err_console.print(
            "[yellow]Note:[/yellow] ffmpeg has no ASS or drawtext filters; "
            "using PNG overlays (slow). Install [bold]ffmpeg-full[/bold]."
        )


@contextmanager
def task(description: str) -> Iterator[None]:
    start = time.perf_counter()
    stop = threading.Event()

    def tick() -> None:
        while not stop.wait(1.0):
            elapsed = time.perf_counter() - start
            status.update(
                f"[bold]{description}[/] [dim]· {format_duration(elapsed)}[/dim]"
            )

    with console.status(f"[bold]{description}[/]", spinner="dots12") as status:
        thread = threading.Thread(target=tick, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=2.0)

    elapsed = time.perf_counter() - start
    label = description.rstrip("…")
    console.print(
        f"[green]✓[/green] [dim]{label} · {format_duration(elapsed)}[/dim]"
    )
