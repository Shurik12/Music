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
    CLI
)
from pathlib import Path


def main() -> None:
    # Create logs directory if it doesn't exist
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
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
        logger.info(f"Config file: {args.config}")
        logger.info(f"Output file: {args.output}")
        logger.info(f"Proxy enabled: {not args.no_proxy}")
        if not args.no_proxy:
            logger.info(f"Proxy port: {args.proxy_port}")
        
        ytmusic_download_dir = config.get("ytmusic_download_dir", "downloads")
        logger.info(f"YouTube Music download directory: {ytmusic_download_dir}")
        
        # Initialize clients
        logger.info("Initializing Yandex.Music client...")
        yamusic = YaMusicHandle(config["token"])
        
        logger.info("Initializing YouTube Music client...")
        ytmusic = YTMusicClient(ytmusic_download_dir)
        
        logger.info("Successfully initialized both clients")
        
        # Start CLI interface
        cli = CLI(yamusic, ytmusic, args)
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