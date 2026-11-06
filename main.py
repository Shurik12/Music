#!/usr/bin/env python3
"""
Yandex.Music to YouTube Music Transfer Tool
Entry point — a thin wrapper around the Typer app in :mod:`src.cli`.
"""

import typer


def main() -> None:
    from src.cli import app
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("Interrupted.")
        raise typer.Exit(code=0)


if __name__ == "__main__":
    main()
