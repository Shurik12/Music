"""Typer sub-commands for Buildin AI / MCP (formerly the ``buildin`` menu)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from typer import Context, Option

from .buildin import BuildinError
from .buildin_maps import MapSyncError, export_maps, import_maps, write_imported_maps
from .cli_base import CliContext, get_context

buildin = typer.Typer(help="Buildin.ai MCP client: OAuth, tools, and playlist-map sync.")
console = Console()


def _ensure_login(c: CliContext) -> bool:
    """Return True if we can talk to Buildin; otherwise try to log in interactively."""
    if c.buildin.is_authorized():
        return True
    console.print("Buildin authorization required for this command.")
    return _login(c)


def _login(c: CliContext) -> bool:
    try:
        data = c.buildin.login()
    except BuildinError as e:
        console.print(f"[red]Buildin login failed:[/red] {e}")
        return False
    except Exception as e:  # pragma: no cover - defensive
        console.print(f"[red]Buildin login failed:[/red] {type(e).__name__}: {e}")
        return False

    expires_at = data.get("expires_at")
    if expires_at:
        expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"Logged in to Buildin MCP. Access token expires at {expires} (auto-refreshed).")
    else:
        console.print("Logged in to Buildin MCP.")
    return True


@buildin.command("login")
def login(ctx: Context) -> None:
    """Log in via browser OAuth (PKCE, local 127.0.0.1 callback)."""
    c: CliContext = get_context(ctx)
    _login(c)


@buildin.command("status")
def status(ctx: Context) -> None:
    """Show the current Buildin authorization status."""
    c: CliContext = get_context(ctx)
    s = c.buildin.status()
    console.print(f"MCP endpoint: {s['mcp_url']}")
    console.print(f"Token file:   {s['token_file']}")
    if not s["authorized"]:
        console.print("Status:       [red]not authorized[/red] (run 'buildin login')")
        return
    import os

    if os.environ.get("BUILDIN_ACCESS_TOKEN"):
        console.print("Status:       [green]authorized via BUILDIN_ACCESS_TOKEN[/green]")
        return
    expires_at = s.get("expires_at")
    if expires_at:
        expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"Status:       [green]authorized[/green] (token expires at {expires})")
    else:
        console.print("Status:       [green]authorized[/green]")


@buildin.command("tools")
def tools(ctx: Context) -> None:
    """List the tools exposed by the Buildin MCP server."""
    c: CliContext = get_context(ctx)
    if not _ensure_login(c):
        raise typer.Exit(code=1)
    try:
        list = c.buildin.list_tools()
    except BuildinError as e:
        raise typer.Abort(f"Could not list Buildin tools: {e}")

    if not list:
        console.print("The Buildin MCP server exposes no tools.")
        return

    console.print(f"{len(list)} Buildin MCP tools:")
    for tool in list:
        name = tool.get("name", "?")
        description = " ".join((tool.get("description") or "").split())
        if description:
            console.print(f"  - {name}: {description[:140]}")
        else:
            console.print(f"  - {name}")


@buildin.command("call")
def call(
    ctx: Context,
    name: str = Option(..., "--tool", "-t", help="Name of the MCP tool to call."),
    args_json: Optional[str] = Option(
        None,
        "--args",
        "-a",
        help='Arguments as a JSON object (default "{}").',
    ),
) -> None:
    """Call an arbitrary Buildin MCP tool with JSON arguments."""
    c: CliContext = get_context(ctx)
    if not _ensure_login(c):
        raise typer.Exit(code=1)

    arguments: dict = {}
    if args_json:
        try:
            arguments = json.loads(args_json)
        except json.JSONDecodeError as e:
            raise typer.Abort(f"Invalid JSON arguments: {e}")
        if not isinstance(arguments, dict):
            raise typer.Abort("Arguments must be a JSON object.")

    try:
        result = c.buildin.call_tool(name, arguments)
    except BuildinError as e:
        raise typer.Abort(f"Buildin tool call failed: {e}")

    _print_tool_result(result)


def _print_tool_result(result) -> None:
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                console.print(item.get("text", ""))
            else:
                console.print_json(json.dumps(item))
    else:
        console.print_json(json.dumps(result))

    if isinstance(result, dict) and result.get("isError"):
        console.print("[yellow](the tool reported an error)[/yellow]")


@buildin.command("logout")
def logout(ctx: Context) -> None:
    """Remove stored Buildin OAuth tokens."""
    c: CliContext = get_context(ctx)
    c.buildin.logout()
    console.print("Buildin tokens removed.")


@buildin.command("export-maps")
def export_maps_cmd(ctx: Context) -> None:
    """Export local playlist maps to the Buildin page/database."""
    c: CliContext = get_context(ctx)
    if not _ensure_login(c):
        raise typer.Exit(code=1)
    console.print("Exporting local playlist maps to Buildin...")
    try:
        result = export_maps(c.buildin)
    except MapSyncError as e:
        raise typer.Abort(f"Buildin export failed: {e}")

    console.print(f"Page:     {result['page_id']}")
    console.print(f"Database: {result['database_id']}")
    console.print(
        f"Records:  {result['created']} created, {result['updated']} updated, "
        f"{result['unchanged']} unchanged (total {result['total']})"
    )
    if result["orphaned"]:
        console.print("[yellow]Orphaned in Buildin[/yellow] (no local counterpart; delete manually in the UI):")
        for platform, title in result["orphaned"]:
            console.print(f"  - {platform}: {title}")


@buildin.command("import-maps")
def import_maps_cmd(
    ctx: Context,
    yes: bool = Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Import playlist maps from Buildin, writing to the local YAML files."""
    c: CliContext = get_context(ctx)
    if not _ensure_login(c):
        raise typer.Exit(code=1)
    console.print("Reading playlist maps from Buildin...")
    try:
        result = import_maps(c.buildin)
    except MapSyncError as e:
        raise typer.Abort(f"Buildin import failed: {e}")

    console.print(
        f"Records: {result['records']} | YouTube: {len(result['youtube'])} | "
        f"Yandex: {len(result['yandex'])}"
    )
    for platform, key in (("YouTube", "youtube_diff"), ("Yandex", "yandex_diff")):
        diff = result[key]
        console.print(
            f"{platform} changes vs local: +{len(diff['added'])} "
            f"-{len(diff['removed'])} ~{len(diff['changed'])}"
        )
        for label in ("added", "removed", "changed"):
            values = diff[label]
            for value in values[:10]:
                console.print(f"  {label}: {value}")
            if len(values) > 10:
                console.print(f"  ... {len(values) - 10} more {label}")

    if not result["youtube"]:
        console.print("No YouTube records in Buildin — data/playlists_map.yaml will be kept.")
    if not result["yandex"]:
        console.print("No Yandex records in Buildin — data/yamusic.yaml will be kept.")
    if not result["youtube"] and not result["yandex"]:
        return

    if not yes:
        if not typer.confirm("\nOverwrite local YAML maps with the Buildin data?"):
            console.print("Import cancelled.")
            raise typer.Exit(code=1)

    written = write_imported_maps(result)
    console.print("Written:")
    for path in written:
        console.print(f"  [bold]{path}[/bold] (backup: {path}.bak)")
