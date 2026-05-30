"""AcoustID song identification with on-disk cache."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import acoustid
import typer

CACHE_DIR = Path(".acoustid")
MIN_MATCH_SCORE = 0.5


@dataclass(frozen=True)
class SongMatch:
    title: str | None
    artist: str | None
    recording_id: str | None
    score: float

    @property
    def matched(self) -> bool:
        return self.score >= MIN_MATCH_SCORE and bool(self.title or self.artist)


def get_api_key() -> str:
    api_key = os.environ.get("ACOUSTID_API_KEY")
    if not api_key:
        raise typer.BadParameter(
            "ACOUSTID_API_KEY is not set. Export it in your environment before running."
        )
    return api_key


def format_song_name(match: SongMatch | None, path: Path) -> str:
    if match and match.matched:
        if match.artist and match.title:
            return f"{match.artist} — {match.title}"
        return match.title or match.artist or path.name
    return path.name


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_path(path: Path) -> Path:
    return CACHE_DIR / f"{_file_fingerprint(path)}.json"


def _read_cache(path: Path) -> SongMatch | None:
    cache_file = _cache_path(path)
    if not cache_file.exists():
        return None

    try:
        data = json.loads(cache_file.read_text())
    except json.JSONDecodeError:
        return None

    stat = path.stat()
    if data.get("mtime_ns") != stat.st_mtime_ns or data.get("size") != stat.st_size:
        return None

    match_data = data.get("match")
    if match_data is None:
        return SongMatch(None, None, None, 0.0)

    return SongMatch(
        title=match_data.get("title"),
        artist=match_data.get("artist"),
        recording_id=match_data.get("recording_id"),
        score=float(match_data.get("score", 0.0)),
    )


def _write_cache(path: Path, match: SongMatch) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    stat = path.stat()
    payload = {
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
        "source": path.name,
        "match": asdict(match) if match.matched else None,
    }
    _cache_path(path).write_text(json.dumps(payload, indent=2))


def _lookup_remote(path: Path, api_key: str) -> SongMatch:
    best_score = 0.0
    best_recording_id: str | None = None
    best_title: str | None = None
    best_artist: str | None = None

    for score, recording_id, title, artist in acoustid.match(api_key, str(path)):
        if score > best_score:
            best_score = score
            best_recording_id = recording_id
            best_title = title
            best_artist = artist

    return SongMatch(
        title=best_title,
        artist=best_artist,
        recording_id=best_recording_id,
        score=best_score,
    )


def identify_song(path: Path, api_key: str, *, use_cache: bool = True) -> SongMatch:
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    try:
        match = _lookup_remote(path, api_key)
    except acoustid.NoBackendError as exc:
        raise typer.BadParameter(
            "Chromaprint is required. Install fpcalc, e.g. `brew install chromaprint`."
        ) from exc
    except acoustid.AcoustidError as exc:
        raise typer.BadParameter(f"AcoustID lookup failed for {path.name}: {exc}") from exc

    if use_cache:
        _write_cache(path, match)

    return match


def identify_songs(
    paths: list[Path], api_key: str, *, use_cache: bool = True
) -> dict[Path, SongMatch]:
    return {path: identify_song(path, api_key, use_cache=use_cache) for path in paths}
