"""ffprobe helpers for inspecting media files."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from go_out.ffmpeg import ffprobe_binary


@dataclass(frozen=True)
class VideoProbe:
    path: Path
    codec: str
    width: int
    height: int
    duration: float
    file_size: int
    video_bitrate_bps: int | None
    format_bitrate_bps: int | None
    estimated_video_bitrate_bps: int | None
    audio_codec: str | None
    audio_bitrate_bps: int | None

    @property
    def resolution(self) -> str:
        return f"{self.width}×{self.height}"

    @property
    def suggested_auto_bitrate(self) -> str | None:
        """Target for ``--bitrate auto`` (~90% of best video bitrate estimate)."""
        source_bps = self.video_bitrate_bps or self.estimated_video_bitrate_bps
        if source_bps is None:
            return None
        return format_ffmpeg_bitrate(max(500_000, int(source_bps * 0.9)))


def _stream_bitrate(stream: dict) -> int | None:
    rate = stream.get("bit_rate")
    if rate is None:
        return None
    value = int(rate)
    return value if value > 0 else None


def _estimate_video_bitrate_bps(
    *,
    file_size: int,
    duration: float,
    audio_bitrate_bps: int | None,
) -> int | None:
    if file_size <= 0 or duration <= 0:
        return None
    total_bps = int(file_size * 8 / duration)
    if audio_bitrate_bps is not None:
        return max(total_bps - audio_bitrate_bps, total_bps // 2)
    return max(total_bps - 128_000, total_bps // 2)


def probe_video(path: Path) -> VideoProbe:
    """Inspect a video file with ffprobe."""
    output = subprocess.check_output(
        [
            ffprobe_binary(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "stream=codec_type,codec_name,bit_rate,width,height",
            "-show_entries",
            "format=bit_rate,duration,size",
            str(path),
        ],
        text=True,
    )
    data = json.loads(output)
    fmt = data.get("format", {})

    video_stream: dict | None = None
    audio_stream: dict | None = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if video_stream is None:
        raise ValueError(f"No video stream found in {path}")

    file_size = int(fmt["size"]) if fmt.get("size") else 0
    duration = float(fmt["duration"]) if fmt.get("duration") else 0.0
    format_bitrate_bps = _stream_bitrate(fmt)
    video_bitrate_bps = _stream_bitrate(video_stream)
    audio_bitrate_bps = _stream_bitrate(audio_stream) if audio_stream else None

    return VideoProbe(
        path=path,
        codec=str(video_stream.get("codec_name", "unknown")),
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        duration=duration,
        file_size=file_size,
        video_bitrate_bps=video_bitrate_bps,
        format_bitrate_bps=format_bitrate_bps,
        estimated_video_bitrate_bps=_estimate_video_bitrate_bps(
            file_size=file_size,
            duration=duration,
            audio_bitrate_bps=audio_bitrate_bps,
        ),
        audio_codec=(
            str(audio_stream["codec_name"]) if audio_stream is not None else None
        ),
        audio_bitrate_bps=audio_bitrate_bps,
    )


def probe_video_size(path: Path) -> tuple[int, int]:
    probe = probe_video(path)
    return probe.width, probe.height


def probe_video_bitrate_bps(path: Path) -> int | None:
    """Return the best available video bitrate estimate in bits/s."""
    probe = probe_video(path)
    return probe.video_bitrate_bps or probe.estimated_video_bitrate_bps


def format_human_bitrate(bps: int | None) -> str:
    if bps is None:
        return "—"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    return f"{bps / 1_000:.0f} kbps"


def format_ffmpeg_bitrate(bps: int) -> str:
    """Format bits/s for ffmpeg ``-b:v`` (e.g. ``8M``, ``4500k``)."""
    if bps >= 1_000_000:
        mbps = bps / 1_000_000
        if abs(mbps - round(mbps)) < 0.05:
            return f"{round(mbps)}M"
        return f"{mbps:.1f}M"
    return f"{max(1, bps // 1000)}k"


def format_file_size(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.2f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.1f} KB"
    return f"{size} B"


def resolve_video_bitrate(video_path: Path, bitrate: str) -> str:
    """Resolve ``auto`` or validate and normalise an explicit bitrate string."""
    if bitrate.lower() == "auto":
        source_bps = probe_video_bitrate_bps(video_path)
        if source_bps is None:
            raise ValueError(
                "Could not probe input video bitrate; pass an explicit value "
                "(e.g. --bitrate 8M)."
            )
        target_bps = max(500_000, int(source_bps * 0.9))
        return format_ffmpeg_bitrate(target_bps)

    match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)([kKmM]?)", bitrate.strip())
    if not match:
        raise ValueError(
            f"Invalid bitrate {bitrate!r}; use auto or a value like 8M or 5000k."
        )

    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "m":
        bps = int(number * 1_000_000)
    elif suffix == "k":
        bps = int(number * 1_000)
    else:
        bps = int(number)

    if bps < 100_000:
        raise ValueError("Bitrate must be at least 100k.")

    return format_ffmpeg_bitrate(bps)
