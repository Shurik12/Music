"""Root Typer application for the music library CLI.

Replaces the interactive menu loop of the old ``CLI`` class. Every command in
:mod:`src.cli_ytmusic`, :mod:`src.cli_yamusic`, :mod:`src.cli_buildin` is
mounted as a sub-app; the global options (``--config``, ``--output``,
``--no-proxy``, ``--proxy-port``, ``--log-level``, ``--log-file``) remain
available on every sub-command via Typer's callback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import types

import typer
from rich.console import Console

from .buildin import DEFAULT_MCP_URL
from .buildin import BuildinClient
from .yamusic import YaMusicHandle
from .ytmusic import YTMusicClient
from . import load_config, paths, setup_logging, get_logger
from .args import LogLevel
from .cli_base import CliContext
from .cli_ytmusic import yt
from .cli_yamusic import ya
from .cli_buildin import buildin

app = typer.Typer(
    name="music",
    help="Yandex Music / YouTube Music / Buildin.ai music library CLI.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(yt, name="ytmusic", help="YouTube Music commands.")
app.add_typer(ya, name="yamusic", help="Yandex Music commands.")
app.add_typer(buildin, name="buildin", help="Buildin.ai MCP commands.")


@app.callback()
def root(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Config file (default: config/config.yaml)."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file for transfer results."
    ),
    no_proxy: bool = typer.Option(
        False, "--no-proxy", help="Disable the SOCKS5 proxy (overrides config)."
    ),
    proxy_port: int = typer.Option(
        1080, "--proxy-port", help="Proxy port (1080 for ciadpi, 9150 for Tor)."
    ),
    log_level: LogLevel = typer.Option(
        LogLevel.INFO, "--log-level", help="Logging level."
    ),
    log_file: Optional[str] = typer.Option(
        None, "--log-file", help="Log file name (default: auto-generated with timestamp)."
    ),
) -> None:
    """Global options — apply to every sub-command."""
    paths.ensure_directories()
    logs_dir = paths.LOGS_DIR

    # Redirect a relative --output into logs/, mirroring the old behaviour.
    if output and not Path(output).is_absolute():
        output = logs_dir / output

    setup_logging(log_level.value, str(output) if output else None)
    logger = get_logger(__name__)
    logger.info(f"Config file: {paths.resolve_config(config)}")
    if output:
        logger.info(f"Output file: {output}")
    logger.info(f"Proxy enabled: {not no_proxy}")
    if not no_proxy:
        logger.info(f"Proxy port: {proxy_port}")

    config_data = load_config(config)
    logger.info(f"YouTube Music download dir: {paths.resolve(config_data.get('ytmusic_download_dir', paths.DOWNLOAD_DIR))}")

    logger.info("Initializing Yandex Music client...")
    yamusic = YaMusicHandle(config_data["token"])
    logger.info("Initializing YouTube Music client...")
    ytmusic = YTMusicClient(str(paths.resolve(config_data.get("ytmusic_download_dir", paths.DOWNLOAD_DIR))))
    logger.info("Initializing Buildin MCP client (no network until used)...")
    buildin_cfg = config_data.get("buildin") or {}
    if not isinstance(buildin_cfg, dict):
        raise typer.Abort("config 'buildin' section must be a mapping")
    buildin_url = buildin_cfg.get("mcp_url", DEFAULT_MCP_URL)
    token_file = buildin_cfg.get("token_file")
    buildin = BuildinClient(
        mcp_url=buildin_url,
        token_file=paths.resolve(token_file) if token_file else paths.BUILDIN_TOKENS_FILE,
    )
    logger.info(f"Buildin MCP endpoint: {buildin_url}")

    args = types.SimpleNamespace(
        config=config,
        output=output,
        no_proxy=no_proxy,
        proxy_port=proxy_port,
        log_level=log_level,
        log_file=log_file,
    )

    ctx.obj = CliContext(
        yamusic=yamusic,
        ytmusic=ytmusic,
        buildin=buildin,
        args=args,
    )
    logger.info("Clients initialised; dispatching sub-command...")
