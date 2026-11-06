"""Argument parsing for the CLI.

The old argparse parser is gone; Typer reads the options directly from
:mod:`src.cli`. This module keeps only the shared :class:`LogLevel` enum that
Typer options need to expose ``--log-level`` with proper validation.
"""

from __future__ import annotations

from enum import Enum


class LogLevel(str, Enum):
    """Supported log levels (mirrors the old argparse ``choices``)."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
