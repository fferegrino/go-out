"""Fast final render via FFmpeg (drawtext or PNG overlay + audio mux)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from moviepy.config import FFMPEG_BINARY
from moviepy.tools import ffmpeg_escape_filename, subprocess_call


def _resolve_tool(name: str, moviepy_default: str) -> str:
    """Prefer a system binary on PATH; avoid deriving ffprobe from imageio's ffmpeg."""
    path = shutil.which(name)
    if path:
        return path
    if moviepy_default not in ("ffmpeg", "ffprobe", "unset") and Path(moviepy_default).is_file():
        return moviepy_default
    return name


def ffmpeg_binary() -> str:
    return _resolve_tool("ffmpeg", FFMPEG_BINARY)


def ffprobe_binary() -> str:
    return _resolve_tool("ffprobe", "ffprobe")


@lru_cache(maxsize=1)
def has_drawtext_filter() -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_binary(), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=True,
        )
        return " drawtext " in f" {result.stdout} "
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def probe_video_height(path: Path) -> int:
    output = subprocess.check_output(
        [
            ffprobe_binary(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "stream=height",
            "-select_streams",
            "v:0",
            str(path),
        ],
        text=True,
    )
    stream = json.loads(output)["streams"][0]
    return int(stream["height"])


def _load_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = _default_font()
    if font_path:
        return ImageFont.truetype(font_path, font_size)
    return ImageFont.load_default()


def _default_font() -> str | None:
    for candidate in (
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


def escape_drawtext(text: str) -> str:
    """Escape label text for ffmpeg drawtext inside single quotes."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace("\n", " ")
    )


def make_label_png(text: str, font_size: int, padding: int) -> Image.Image:
    """Render a song title to a transparent PNG for the overlay filter."""
    font = _load_font(font_size)
    stroke = 2

    measure = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(measure)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    width = bbox[2] - bbox[0] + 2 * padding
    height = bbox[3] - bbox[1] + 2 * padding

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=6,
        fill=(0, 0, 0, 180),
    )
    draw.text(
        (padding, padding),
        text,
        font=font,
        fill="white",
        stroke_width=stroke,
        stroke_fill="black",
    )
    return image


def build_drawtext_filter(
    segments: list[tuple[str, float]],
    video_height: int,
) -> str:
    """Build a -vf filter chain with one timed drawtext per segment."""
    font_size = max(24, video_height // 28)
    margin = max(12, video_height // 48)
    font = _default_font()
    font_opt = f"fontfile='{font}':" if font else ""

    filters: list[str] = []
    start = 0.0
    for label, duration in segments:
        end = start + duration
        text = escape_drawtext(label)
        filters.append(
            f"drawtext={font_opt}text='{text}':x={margin}:y={margin}:"
            f"fontsize={font_size}:fontcolor=white:borderw=2:bordercolor=black:"
            f"box=1:boxcolor=black@0.7:boxborderw=8:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
        )
        start = end

    return ",".join(filters)


def build_png_overlay_filter(
    segments: list[tuple[str, float]],
    margin: int,
) -> str:
    """Build a -filter_complex chain using timed PNG overlays."""
    parts: list[str] = []
    start = 0.0
    prev = "0:v"

    for index, (_, duration) in enumerate(segments):
        end = start + duration
        png_input = index + 2  # 0=video, 1=audio, 2+=png
        out = "vout" if index == len(segments) - 1 else f"v{index}"
        parts.append(
            f"[{prev}][{png_input}:v]overlay=x={margin}:y={margin}:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{out}]"
        )
        prev = out
        start = end

    return ";".join(parts)


def _append_video_encoder(cmd: list[str], *, use_hw: bool, preset: str, crf: int) -> None:
    if use_hw:
        cmd.extend(["-c:v", "h264_videotoolbox", "-q:v", "65"])
    else:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-threads",
                "0",
            ]
        )


def _render_with_drawtext(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    video_height: int,
    use_hw: bool,
    preset: str,
    crf: int,
    quiet: bool,
) -> None:
    cmd = [
        ffmpeg_binary(),
        "-y",
        "-i",
        ffmpeg_escape_filename(str(video_path)),
        "-i",
        ffmpeg_escape_filename(str(audio_path)),
        "-vf",
        build_drawtext_filter(segments, video_height),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
    ]
    _append_video_encoder(cmd, use_hw=use_hw, preset=preset, crf=crf)
    cmd.extend(["-c:a", "aac", "-b:a", "192k", ffmpeg_escape_filename(str(output_path))])
    subprocess_call(cmd, logger=None if quiet else "bar")


def _render_with_png_overlays(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    video_height: int,
    use_hw: bool,
    preset: str,
    crf: int,
    quiet: bool,
) -> None:
    font_size = max(24, video_height // 28)
    margin = max(12, video_height // 48)

    with tempfile.TemporaryDirectory(prefix="go-out-labels-") as tmp:
        tmp_dir = Path(tmp)
        for index, (label, _) in enumerate(segments):
            png_path = tmp_dir / f"label_{index:04d}.png"
            make_label_png(label, font_size, padding=12).save(png_path)

        cmd = [
            ffmpeg_binary(),
            "-y",
            "-i",
            ffmpeg_escape_filename(str(video_path)),
            "-i",
            ffmpeg_escape_filename(str(audio_path)),
        ]
        for index in range(len(segments)):
            cmd.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    ffmpeg_escape_filename(str(tmp_dir / f"label_{index:04d}.png")),
                ]
            )

        cmd.extend(
            [
                "-filter_complex",
                build_png_overlay_filter(segments, margin),
                "-map",
                "[vout]",
                "-map",
                "1:a:0",
                "-shortest",
            ]
        )
        _append_video_encoder(cmd, use_hw=use_hw, preset=preset, crf=crf)
        cmd.extend(["-c:a", "aac", "-b:a", "192k", ffmpeg_escape_filename(str(output_path))])
        subprocess_call(cmd, logger=None if quiet else "bar")


def render_video_with_overlays(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    preset: str = "veryfast",
    crf: int = 20,
    hw_encode: bool | None = None,
    quiet: bool = False,
) -> None:
    """Mux audio and burn song titles using a single FFmpeg encode pass."""
    use_hw = hw_encode if hw_encode is not None else sys.platform == "darwin"
    height = probe_video_height(video_path)

    if has_drawtext_filter():
        _render_with_drawtext(
            video_path,
            audio_path,
            segments,
            output_path,
            video_height=height,
            use_hw=use_hw,
            preset=preset,
            crf=crf,
            quiet=quiet,
        )
    else:
        _render_with_png_overlays(
            video_path,
            audio_path,
            segments,
            output_path,
            video_height=height,
            use_hw=use_hw,
            preset=preset,
            crf=crf,
            quiet=quiet,
        )
