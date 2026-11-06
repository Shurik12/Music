"""Typer sub-commands for YouTube Music (formerly the ``ytmusic`` menu)."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from typer import Context, Option

from .cli_base import CliContext, get_context

yt = typer.Typer(help="YouTube Music playlist & download management.")
console = Console()


@yt.command("list-playlists")
def list_playlists(ctx: Context) -> None:
    """List all user playlists."""
    c: CliContext = get_context(ctx)
    try:
        playlists = c.ytmusic.get_playlists()
        c.ytmusic.print_playlists(playlists)
    except Exception as e:
        raise typer.Abort(f"Error listing playlists: {e}")


@yt.command("playlist-artists")
def playlist_artists(
    ctx: Context,
    index: int = Option(1, "--index", "-i", help="Playlist index in the library (default 1)."),
) -> None:
    """Print the artists that appear in a specific playlist."""
    c: CliContext = get_context(ctx)
    try:
        playlists = c.ytmusic.get_playlists()
        if index < 0 or index >= len(playlists):
            raise ValueError(f"index {index} out of range (0..{len(playlists)-1})")
        playlist = c.ytmusic.get_playlist(playlists[index]["playlistId"])
        artists = c.ytmusic.get_playlist_artists(playlist)
        console.rule(playlists[index]["title"])
        for a in sorted(artists):
            console.print(f"  {a}")
    except Exception as e:
        raise typer.Abort(f"Error getting playlist artists: {e}")


@yt.command("tracks-out-of-playlist")
def tracks_out_of_playlist(ctx: Context) -> None:
    """Find liked tracks that are not in any user playlist."""
    c: CliContext = get_context(ctx)
    tracks = c.ytmusic.get_track_out_playlist()
    console.print(f"Found {len(tracks)} tracks in the liked playlist.")


@yt.command("print-tracks")
def print_tracks(ctx: Context) -> None:
    """Dump the liked tracks outside playlists to ``logs/tracks.txt``."""
    c: CliContext = get_context(ctx)
    tracks = c.ytmusic.get_track_out_playlist()
    c.ytmusic.print_tracks(tracks)


@yt.command("update-map")
def update_map(
    ctx: Context,
    output: Optional[str] = Option(
        None, "--output", "-o", help="Where to write the updated map (default: data/playlists_map_updated.yaml)."
    ),
) -> None:
    """Regenerate the YouTube playlist map (``data/playlists_map.yaml``)."""
    c: CliContext = get_context(ctx)
    c.ytmusic.update_playlists_map(output)


@yt.command("distribute")
def distribute(ctx: Context) -> None:
    """Distribute out-of-playlist liked tracks into playlists by artist."""
    c: CliContext = get_context(ctx)
    c.ytmusic.distribute_tracks()


@yt.command("download-all")
def download_all(
    ctx: Context,
    format: str = Option("mp3", "--format", "-f", help="Audio format (mp3, m4a, ...)."),
    quality: str = Option("best", "--quality", "-q", help="best | high | medium | low"),
    no_skip: bool = Option(False, "--no-skip", help="Do not skip already-downloaded tracks."),
    limit: Optional[int] = Option(None, "--limit", help="Maximum number of playlists to process."),
) -> None:
    """Download every user playlist (skipping LM/SE)."""
    c: CliContext = get_context(ctx)
    c.ytmusic.download_all_playlists(
        format_type=format,
        quality=quality,
        skip_existing=not no_skip,
        playlist_limit=limit,
    )


@yt.command("download-track")
def download_track(
    ctx: Context,
    video_id: str = Option(..., "--id", "-v", help="YouTube video ID."),
    quality: str = Option("best", "--quality", "-q", help="best | high | medium | low"),
    format: str = Option("mp3", "--format", "-f", help="Audio format (mp3, m4a, ...)."),
    quiet: bool = Option(False, "--quiet", help="Suppress yt-dlp output."),
) -> None:
    """Download a single track from YouTube by video ID."""
    c: CliContext = get_context(ctx)
    result = c.ytmusic.download_track(
        video_id=video_id,
        format_type=format,
        quality=quality,
        quiet=quiet,
    )
    if result is None:
        raise typer.Exit(code=1)
    console.print(f"Saved: {result}")
