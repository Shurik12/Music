"""Typer sub-commands for Yandex Music (formerly the ``yamusic`` menu)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from typer import Context, Option

from . import paths
from .cli_base import CliContext, get_context

ya = typer.Typer(help="Yandex Music playlist & download management.")
console = Console()


def _write_transfer_report(path: str, data: dict) -> None:
    import json

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


@ya.command("transfer")
def transfer(
    ctx: Context,
    output: Optional[str] = Option(
        None, "--output", "-o",
        help="Where to write the transfer report (default: logs/tracks.json).",
    ),
    yes: bool = Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Transfer liked tracks from Yandex Music to YouTube Music."""
    c: CliContext = get_context(ctx)
    if output is None:
        out = str(c.args.output) if c.args.output else "tracks.json"
    else:
        out = str(output)

    if not yes:
        if not typer.confirm(
            "Transfer liked tracks from Yandex Music to YouTube Music? "
            "(This is destructive on the Yandex side: it removes broken liked tracks.)"
        ):
            console.print("Transfer cancelled.")
            raise typer.Exit(code=1)

    console.print("Exporting liked tracks from Yandex Music...")
    tracks = c.yamusic.export_liked_tracks()
    tracks.reverse()

    data = {
        "liked_tracks": [{"artist": t.artist, "name": t.name} for t in tracks],
        "not_found": [],
        "errors": [],
    }

    console.print("Importing liked tracks into YouTube Music...")
    not_found, errors = c.ytmusic.import_liked_tracks(tracks)

    for t in not_found:
        data["not_found"].append({"artist": t.artist, "name": t.name})
        console.print(f"[yellow]Not found:[/yellow] {t.artist} - {t.name}")
    for t in errors:
        data["errors"].append({"artist": t.artist, "name": t.name})
        console.print(f"[red]Error:[/red] {t.artist} - {t.name}")

    console.print(f"\nTotal: {len(tracks)}")
    console.print(f"Imported: {len(tracks) - len(not_found) - len(errors)}")
    console.print(f"Not found: {len(not_found)}")
    console.print(f"Errors: {len(errors)}")

    _write_transfer_report(out, data)
    console.print(f"Report written to [bold]{out}[/bold]")


@ya.command("download-playlists")
def download_playlists(ctx: Context) -> None:
    """Download every Yandex playlist to ``downloads/``."""
    c: CliContext = get_context(ctx)
    c.yamusic.download_playlists()


@ya.command("download-liked")
def download_liked(ctx: Context) -> None:
    """Download the liked tracks as a single 'Like' playlist."""
    c: CliContext = get_context(ctx)
    c.yamusic.download_like_tracks()


@ya.command("playlist-map")
def playlist_map(
    ctx: Context,
    output: Optional[str] = Option(
        None, "--output", "-o",
        help="Where to write the map (default: data/temp_playlist_map.yaml).",
    ),
) -> None:
    """Generate the Yandex playlist map (``data/yamusic.yaml``)."""
    c: CliContext = get_context(ctx)
    c.yamusic.playlist_map(output)


@ya.command("check-tracks")
def check_tracks(
    ctx: Context,
    yes: bool = Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Remove liked tracks that Yandex can no longer resolve (destructive)."""
    c: CliContext = get_context(ctx)
    if not yes:
        if not typer.confirm(
            "Remove broken liked tracks from Yandex Music? "
            "(This cannot be undone.)"
        ):
            console.print("Cancelled.")
            raise typer.Exit(code=1)
    c.yamusic.check_tracks()


@ya.command("sync-from-yaml")
def sync_from_yaml(
    ctx: Context,
    yaml_file: Optional[str] = Option(
        None, "--file", "-f",
        help="Playlist config YAML (default: data/yamusic.yaml).",
    ),
    yes: bool = Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Clear and repopulate Yandex playlists from the YAML map (destructive)."""
    c: CliContext = get_context(ctx)
    if not yes:
        if not typer.confirm(
            "Sync Yandex playlists from YAML? "
            "This clears each target playlist before repopulating it."
        ):
            console.print("Cancelled.")
            raise typer.Exit(code=1)
    path = yaml_file or str(paths.YAMUSIC_MAP_FILE)
    c.yamusic.sync_playlists_from_yaml(path)
