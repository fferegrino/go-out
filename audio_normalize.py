"""Per-track volume normalization."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pyloudnorm as pyln
from moviepy import AudioArrayClip, AudioFileClip, afx

NormalizeMode = Literal["loudness", "peak"]
DEFAULT_TARGET_LUFS = -12.0


def normalize_clip(
    clip: AudioFileClip,
    *,
    mode: NormalizeMode = "loudness",
    target_lufs: float = DEFAULT_TARGET_LUFS,
) -> AudioFileClip:
    """Return a clip normalized to match other tracks in the playlist."""
    if mode == "peak":
        return clip.with_effects([afx.AudioNormalize()])

    fps = int(clip.fps or 44100)
    samples = clip.to_soundarray(fps=fps)
    if samples.size == 0:
        return clip.with_effects([afx.AudioNormalize()])

    if samples.ndim == 1:
        samples = samples[:, np.newaxis]

    meter = pyln.Meter(fps)
    try:
        loudness = meter.integrated_loudness(samples)
    except ValueError:
        return clip.with_effects([afx.AudioNormalize()])

    if not np.isfinite(loudness):
        return clip.with_effects([afx.AudioNormalize()])

    normalized = pyln.normalize.loudness(samples, loudness, target_lufs)
    normalized = np.clip(normalized, -1.0, 1.0)

    if normalized.ndim == 2 and normalized.shape[1] == 1:
        normalized = normalized[:, 0]

    return AudioArrayClip(normalized, fps=fps).with_duration(clip.duration)
