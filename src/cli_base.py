"""Shared Typer app + context factory.

The interactive menu (formerly ``CLI`` in :mod:`src.cli`) is replaced by a
command tree built with Typer. :mod:`main` constructs a :class:`CliContext`
once, passes it to the root app via ``Typer(context_object=ctx)`` and runs.
Leaf commands in :mod:`src.cli` pull the context off Typer's ``ctx`` and call
the underlying clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import typer
from typer import Context

from .buildin import BuildinClient
from .yamusic import YaMusicHandle
from .ytmusic import YTMusicClient


@dataclass
class CliContext:
    """Holds the initialised clients and the parsed global options."""

    yamusic: YaMusicHandle
    ytmusic: YTMusicClient
    buildin: BuildinClient
    args: Any  # the global options namespace (see :mod:`src.args`)


def get_context(ctx: Context) -> CliContext:
    """Extract :class:`CliContext` from the Typer context (for sub-commands)."""
    if ctx.obj is None:
        raise RuntimeError("CLI context missing; did main() forget to pass context_object?")
    return ctx.obj


def require_context(ctx: Context) -> CliContext:
    """Convenience wrapper that aborts cleanly if the context is missing."""
    try:
        return get_context(ctx)
    except RuntimeError as e:
        raise typer.Abort(str(e))
