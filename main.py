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
    # Override output path to use logs folder if not absolute path
    if args.output and not Path(args.output).is_absolute():
        args.output = str(logs_dir / args.output)
    
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
        yamusic = YaMusicHandle(config["token"])
        
        logger.info("Initializing YouTube Music client...")
        ytmusic = YTMusicClient(str(ytmusic_download_dir))
        
        logger.info("Successfully initialized music clients")
        
        # Buildin AI (MCP) client; no network access until a command needs it
        buildin_config = config.get("buildin") or {}
        if not isinstance(buildin_config, dict):
            raise ValueError("config 'buildin' section must be a mapping")
        buildin_url = buildin_config.get("mcp_url", DEFAULT_MCP_URL)
        token_file = buildin_config.get("token_file")
        buildin = BuildinClient(
            mcp_url=buildin_url,
            token_file=paths.resolve(token_file) if token_file else paths.BUILDIN_TOKENS_FILE,
        )
        logger.info(f"Buildin MCP endpoint: {buildin_url}")
        
        # Start CLI interface
        cli = CLI(yamusic, ytmusic, buildin, args)
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