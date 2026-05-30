"""Resolve ffmpeg and ffprobe binary paths."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from moviepy.config import FFMPEG_BINARY

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
