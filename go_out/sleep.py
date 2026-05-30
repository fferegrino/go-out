"""Keep the system awake during long processing runs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def prevent_system_sleep(enabled: bool = True) -> Iterator[None]:
    """Prevent idle sleep while the wrapped block runs (macOS ``caffeinate``)."""
    if not enabled or sys.platform != "darwin":
        yield
        return

    caffeinate = shutil.which("caffeinate")
    if caffeinate is None:
        yield
        return

    # -d display, -i idle, -m disk, -s AC power system sleep
    proc = subprocess.Popen([caffeinate, "-dims"])
    try:
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def default_prevent_sleep() -> bool:
    return sys.platform == "darwin"
