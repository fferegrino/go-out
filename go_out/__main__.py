"""CLI entry point for ``python -m go_out`` and the ``go-out`` console script."""

from __future__ import annotations

from go_out.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
