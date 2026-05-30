"""Fast final render via FFmpeg (ASS subtitles, drawtext, or PNG overlay + audio mux)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from moviepy.config import FFMPEG_BINARY
from moviepy.tools import ffmpeg_escape_filename, subprocess_call

_cli_ffmpeg: str | None = None
_cli_ffprobe: str | None = None


def set_ffmpeg_binaries(
    ffmpeg: Path | str | None = None,
    ffprobe: Path | str | None = None,
) -> None:
    """Set ffmpeg/ffprobe paths from CLI args or environment variables.

    Priority when resolving (see ``ffmpeg_binary`` / ``ffprobe_binary``):
    1. Explicit CLI values passed here
    2. ``FFMPEG_BINARY`` / ``FFPROBE_BINARY`` environment variables
    3. ``ffmpeg`` / ``ffprobe`` on ``PATH``
    """
    global _cli_ffmpeg, _cli_ffprobe

    if ffmpeg is not None:
        _cli_ffmpeg = str(ffmpeg)
    elif os.environ.get("FFMPEG_BINARY"):
        _cli_ffmpeg = os.environ["FFMPEG_BINARY"]

    if ffprobe is not None:
        _cli_ffprobe = str(ffprobe)
    elif os.environ.get("FFPROBE_BINARY"):
        _cli_ffprobe = os.environ["FFPROBE_BINARY"]
    elif _cli_ffmpeg:
        sibling = Path(_cli_ffmpeg).with_name("ffprobe")
        if sibling.is_file():
            _cli_ffprobe = str(sibling)

    has_drawtext_filter.cache_clear()
    has_subtitles_filter.cache_clear()


def _pick_binary(
    cli_override: str | None,
    env_var: str,
    path_name: str,
    moviepy_default: str,
) -> str:
    candidates = [
        cli_override,
        os.environ.get(env_var),
        shutil.which(path_name),
    ]
    if moviepy_default not in (path_name, "unset") and Path(moviepy_default).is_file():
        candidates.append(moviepy_default)

    for candidate in candidates:
        if not candidate:
            continue
        if candidate == path_name or Path(candidate).is_file():
            return candidate
    return path_name


def ffmpeg_binary() -> str:
    return _pick_binary(_cli_ffmpeg, "FFMPEG_BINARY", "ffmpeg", FFMPEG_BINARY)


def ffprobe_binary() -> str:
    return _pick_binary(_cli_ffprobe, "FFPROBE_BINARY", "ffprobe", "ffprobe")


def _ffmpeg_filters() -> str:
    try:
        result = subprocess.run(
            [ffmpeg_binary(), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


@lru_cache(maxsize=1)
def has_drawtext_filter() -> bool:
    return " drawtext " in f" {_ffmpeg_filters()} "


@lru_cache(maxsize=1)
def has_subtitles_filter() -> bool:
    return " subtitles " in f" {_ffmpeg_filters()} "


def probe_video_size(path: Path) -> tuple[int, int]:
    output = subprocess.check_output(
        [
            ffprobe_binary(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "stream=width,height",
            "-select_streams",
            "v:0",
            str(path),
        ],
        text=True,
    )
    stream = json.loads(output)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def probe_video_height(path: Path) -> int:
    return probe_video_size(path)[1]


def label_render_mode() -> str:
    """Return the label method that ``render_video_with_overlays`` will use."""
    if has_subtitles_filter():
        return "ass"
    if has_drawtext_filter():
        return "drawtext"
    return "png"


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


def _default_font_name() -> str:
    font = _default_font()
    if font and "Arial" in font:
        return "Arial Bold"
    if font and "DejaVu" in font:
        return "DejaVu Sans Bold"
    return "Arial Bold"


def _fonts_dir() -> str | None:
    for candidate in (
        Path("/System/Library/Fonts/Supplemental"),
        Path("/usr/share/fonts/truetype/dejavu"),
    ):
        if candidate.is_dir():
            return str(candidate)
    return None


def _label_metrics(video_height: int) -> tuple[int, int]:
    font_size = max(24, video_height // 28)
    margin = max(12, video_height // 48)
    return font_size, margin


def _scaled_width(source_width: int, source_height: int, target_height: int) -> int:
    width = source_width * target_height // source_height
    return max(2, width // 2 * 2)


def _output_dimensions(
    source_width: int,
    source_height: int,
    scale_height: int | None,
) -> tuple[int, int]:
    if scale_height is None:
        return source_width, source_height
    return _scaled_width(source_width, source_height, scale_height), scale_height


def escape_drawtext(text: str) -> str:
    """Escape label text for ffmpeg drawtext inside single quotes."""
    return (
        text.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace("\n", " ")
    )


def escape_ass_text(text: str) -> str:
    """Escape label text for ASS dialogue lines."""
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def escape_subtitles_path(path: Path) -> str:
    """Escape an ASS path for the ffmpeg subtitles filter."""
    escaped = str(path.resolve()).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return f"'{escaped}'"


def format_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    whole_secs = int(secs)
    centis = int(round((secs - whole_secs) * 100))
    if centis == 100:
        whole_secs += 1
        centis = 0
    return f"{hours}:{minutes:02d}:{whole_secs:02d}.{centis:02d}"


def write_ass_file(
    path: Path,
    segments: list[tuple[str, float]],
    *,
    width: int,
    height: int,
) -> None:
    """Write a timed ASS subtitle file matching drawtext label styling."""
    font_size, margin = _label_metrics(height)
    font_name = _default_font_name()

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,2,0,7,{margin},0,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    start = 0.0
    for label, duration in segments:
        end = start + duration
        text = escape_ass_text(label)
        lines.append(
            f"Dialogue: 0,{format_ass_time(start)},{format_ass_time(end)},"
            f"Default,,0,0,0,,{text}\n"
        )
        start = end

    path.write_text("".join(lines), encoding="utf-8")


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


def build_scale_filter(scale_height: int | None) -> str | None:
    if scale_height is None:
        return None
    return f"scale=-2:{scale_height}"


def build_drawtext_filter(
    segments: list[tuple[str, float]],
    video_height: int,
) -> str:
    """Build a -vf filter chain with one timed drawtext per segment."""
    font_size, margin = _label_metrics(video_height)
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


def build_subtitles_filter(ass_path: Path) -> str:
    fonts_dir = _fonts_dir()
    path = escape_subtitles_path(ass_path)
    if fonts_dir:
        escaped_dir = fonts_dir.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
        return f"subtitles={path}:fontsdir='{escaped_dir}'"
    return f"subtitles={path}"


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


def _hwaccel_args() -> list[str]:
    if sys.platform == "darwin":
        return ["-hwaccel", "videotoolbox"]
    return []


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


def _append_audio_codec(cmd: list[str], *, copy_audio: bool) -> None:
    if copy_audio:
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])


def _join_video_filters(*parts: str | None) -> str:
    return ",".join(part for part in parts if part)


def _render_with_ass(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    output_width: int,
    output_height: int,
    scale_height: int | None,
    use_hw: bool,
    preset: str,
    crf: int,
    copy_audio: bool,
    quiet: bool,
) -> None:
    with tempfile.TemporaryDirectory(prefix="go-out-labels-") as tmp:
        ass_path = Path(tmp) / "labels.ass"
        write_ass_file(
            ass_path,
            segments,
            width=output_width,
            height=output_height,
        )

        cmd = [
            ffmpeg_binary(),
            "-y",
            *_hwaccel_args(),
            "-i",
            ffmpeg_escape_filename(str(video_path)),
            "-i",
            ffmpeg_escape_filename(str(audio_path)),
            "-vf",
            _join_video_filters(
                build_scale_filter(scale_height),
                build_subtitles_filter(ass_path),
            ),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
        ]
        _append_video_encoder(cmd, use_hw=use_hw, preset=preset, crf=crf)
        _append_audio_codec(cmd, copy_audio=copy_audio)
        cmd.append(ffmpeg_escape_filename(str(output_path)))
        subprocess_call(cmd, logger=None if quiet else "bar")


def _render_with_drawtext(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    output_height: int,
    scale_height: int | None,
    use_hw: bool,
    preset: str,
    crf: int,
    copy_audio: bool,
    quiet: bool,
) -> None:
    cmd = [
        ffmpeg_binary(),
        "-y",
        *_hwaccel_args(),
        "-i",
        ffmpeg_escape_filename(str(video_path)),
        "-i",
        ffmpeg_escape_filename(str(audio_path)),
        "-vf",
        _join_video_filters(
            build_scale_filter(scale_height),
            build_drawtext_filter(segments, output_height),
        ),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-shortest",
    ]
    _append_video_encoder(cmd, use_hw=use_hw, preset=preset, crf=crf)
    _append_audio_codec(cmd, copy_audio=copy_audio)
    cmd.append(ffmpeg_escape_filename(str(output_path)))
    subprocess_call(cmd, logger=None if quiet else "bar")


def _render_with_png_overlays(
    video_path: Path,
    audio_path: Path,
    segments: list[tuple[str, float]],
    output_path: Path,
    *,
    output_height: int,
    scale_height: int | None,
    use_hw: bool,
    preset: str,
    crf: int,
    copy_audio: bool,
    quiet: bool,
) -> None:
    font_size, margin = _label_metrics(output_height)

    with tempfile.TemporaryDirectory(prefix="go-out-labels-") as tmp:
        tmp_dir = Path(tmp)
        for index, (label, _) in enumerate(segments):
            png_path = tmp_dir / f"label_{index:04d}.png"
            make_label_png(label, font_size, padding=12).save(png_path)

        scale = build_scale_filter(scale_height)
        overlay = build_png_overlay_filter(segments, margin)
        if scale:
            if ";" in overlay:
                first, rest = overlay.split(";", 1)
                scaled_first = first.replace("[0:v]", "[scaled]", 1)
                filter_complex = f"[0:v]{scale}[scaled];{scaled_first};{rest}"
            else:
                scaled_overlay = overlay.replace("[0:v]", "[scaled]", 1)
                filter_complex = f"[0:v]{scale}[scaled];{scaled_overlay}"
        else:
            filter_complex = overlay

        cmd = [
            ffmpeg_binary(),
            "-y",
            *_hwaccel_args(),
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
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "1:a:0",
                "-shortest",
            ]
        )
        _append_video_encoder(cmd, use_hw=use_hw, preset=preset, crf=crf)
        _append_audio_codec(cmd, copy_audio=copy_audio)
        cmd.append(ffmpeg_escape_filename(str(output_path)))
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
    scale_height: int | None = None,
    copy_audio: bool = True,
    quiet: bool = False,
) -> None:
    """Mux audio and burn song titles using a single FFmpeg encode pass."""
    use_hw = hw_encode if hw_encode is not None else sys.platform == "darwin"
    source_width, source_height = probe_video_size(video_path)
    output_width, output_height = _output_dimensions(
        source_width, source_height, scale_height
    )
    mode = label_render_mode()

    if mode == "ass":
        _render_with_ass(
            video_path,
            audio_path,
            segments,
            output_path,
            output_width=output_width,
            output_height=output_height,
            scale_height=scale_height,
            use_hw=use_hw,
            preset=preset,
            crf=crf,
            copy_audio=copy_audio,
            quiet=quiet,
        )
    elif mode == "drawtext":
        _render_with_drawtext(
            video_path,
            audio_path,
            segments,
            output_path,
            output_height=output_height,
            scale_height=scale_height,
            use_hw=use_hw,
            preset=preset,
            crf=crf,
            copy_audio=copy_audio,
            quiet=quiet,
        )
    else:
        _render_with_png_overlays(
            video_path,
            audio_path,
            segments,
            output_path,
            output_height=output_height,
            scale_height=scale_height,
            use_hw=use_hw,
            preset=preset,
            crf=crf,
            copy_audio=copy_audio,
            quiet=quiet,
        )
