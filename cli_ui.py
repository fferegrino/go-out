"""Rich terminal UI for go-out."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from acoustid_lookup import SongMatch
from video_render import ffmpeg_binary, has_drawtext_filter

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
    identify: bool,
    encoder: str,
    label_mode: str,
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
    table.add_row("Duration", format_duration(video_duration))
    table.add_row("FFmpeg", ffmpeg_binary())
    table.add_row("Encoder", encoder)
    table.add_row("Labels", label_mode)
    table.add_row("Identify", "on" if identify else "off")
    table.add_row("Normalize", "on" if normalize else "off")
    if seed is not None:
        table.add_row("Seed", str(seed))

    console.print(table)


def print_identification_results(
    rows: list[tuple[str, str, SongMatch]],
) -> None:
    table = Table(
        title="AcoustID",
        caption="Cached in .acoustid/",
        box=box.SIMPLE_HEAD,
    )
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Detected title")
    table.add_column("Match", justify="right", width=8)

    for filename, title, match in rows:
        score = (
            f"[green]{match.score:.0%}[/]"
            if match.matched
            else "[dim]—[/dim]"
        )
        table.add_row(filename, title, score)

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
) -> None:
    console.print()
    console.print(
        Panel(
            f"[bold green]✓[/bold green]  [bold]{output}[/bold]\n\n"
            f"[dim]{segment_count} segments · {encoder} · {label_mode}[/dim]",
            title="Finished",
            border_style="green",
            padding=(1, 2),
        )
    )


def label_mode_name() -> str:
    return "drawtext" if has_drawtext_filter() else "PNG overlay"


def note_png_fallback() -> None:
    if not has_drawtext_filter():
        err_console.print(
            "[yellow]Note:[/yellow] ffmpeg has no drawtext filter; using PNG overlays."
        )


@contextmanager
def task(description: str) -> Iterator[None]:
    with console.status(f"[bold]{description}[/]", spinner="dots12"):
        yield
