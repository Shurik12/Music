#!/usr/bin/env python3
"""
Yandex.Music to YouTube Music Transfer Tool
Main entry point
"""

from src import (
    load_config,
    parse_args,
    setup_logging,
    get_logger,
    YaMusicHandle,
    YTMusicClient,
    BuildinClient,
    TelegramClient,
    TelegramUserClient,
    YandexDiskClient,
    CLI
)
from src.buildin import DEFAULT_MCP_URL
from src import paths
from pathlib import Path


def main() -> None:
    # Create the directories the app writes to (all anchored to the repo root)
    paths.ensure_directories()
    logs_dir = paths.LOGS_DIR
    
    # Parse command line arguments
    args = parse_args()
    
    # Setup logging first - use logs directory
    # All output paths are anchored to the repo root via paths.resolve()
    args.output = str(paths.resolve(args.output))
    
    setup_logging(args.log_level, args.output)
    logger = get_logger(__name__)
    
    try:
        # Load configuration
        config = load_config(args.config)
        
        # Log configuration info
        logger.info("Starting Yandex.Music to YouTube Music transfer")
        logger.info(f"Config file: {paths.resolve_config(args.config)}")
        logger.info(f"Output file: {args.output}")
        logger.info(f"Proxy enabled: {not args.no_proxy}")
        if not args.no_proxy:
            logger.info(f"Proxy port: {args.proxy_port}")
        
        ytmusic_download_dir = paths.resolve(
            config.get("ytmusic_download_dir", paths.DOWNLOAD_DIR)
        )
        logger.info(f"YouTube Music download directory: {ytmusic_download_dir}")
        
        # Initialize clients
        logger.info("Initializing Yandex.Music client...")
        yamusic = YaMusicHandle(config["yamusic_token"])
        
        logger.info("Initializing YouTube Music client...")
        ytmusic_config = config.get("ytmusic") or {}
        if not isinstance(ytmusic_config, dict):
            raise ValueError("config 'ytmusic' section must be a mapping")
        yt_auth = ytmusic_config.get("auth")
        if yt_auth is not None and not isinstance(yt_auth, dict):
            raise ValueError("config 'ytmusic.auth' must be a mapping of HTTP headers")
        ytmusic = YTMusicClient(str(ytmusic_download_dir), auth=yt_auth)
        
        logger.info("Successfully initialized music clients")
        
        # Buildin AI (MCP) client; no network access until a command needs it
        buildin_config = config.get("buildin") or {}
        if not isinstance(buildin_config, dict):
            raise ValueError("config 'buildin' section must be a mapping")
        buildin_url = buildin_config.get("mcp_url", DEFAULT_MCP_URL)
        buildin = BuildinClient(
            mcp_url=buildin_url,
            config_path=paths.resolve_config(args.config),
        )
        logger.info(f"Buildin MCP endpoint: {buildin_url}")

        # Telegram bot (Bot API); optional — no network access until a command
        # uses it. Configured via the `telegram:` section of config.yaml.
        telegram_config = config.get("telegram") or {}
        if not isinstance(telegram_config, dict):
            raise ValueError("config 'telegram' section must be a mapping")
        telegram = TelegramClient(telegram_config)
        logger.info("Telegram bot: configured" if telegram.token else "Telegram bot: not configured (no telegram.token)")
        # Telegram user account (MTProto session), for Saved Messages / dialogs.
        # Lazy: no connection until a Telegram menu action needs it.
        telegram_user = TelegramUserClient(telegram_config)
        logger.info(
            "Telegram user session: %s",
            "configured" if telegram_user.configured else "not configured (no telegram.api_id/api_hash)",
        )

        # Yandex Disk (REST); lazy — no network until a command uses it.
        yandex_disk = YandexDiskClient(config_path=paths.resolve_config(args.config))
        logger.info(
            "Yandex Disk: %s",
            "configured" if yandex_disk.is_authorized() else "not logged in (use Yandex Disk → Log in)",
        )

        # Start CLI interface
        cli = CLI(yamusic, ytmusic, buildin, args, telegram, telegram_user, yandex_disk=yandex_disk)
        cli.run()
        
        logger.info("Transfer completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Transfer interrupted by user")
        exit(0)
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        exit(1)


if __name__ == "__main__":
    main()