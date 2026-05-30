"""CLI entry point for ``python -m go_out`` and the ``go-out`` console script."""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "probe":
        from go_out.probe_cli import app as probe_app

        sys.argv.pop(1)
        probe_app()
    else:
        from go_out.cli import app

        app()


if __name__ == "__main__":
    main()
