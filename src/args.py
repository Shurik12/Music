import argparse


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Transfer tracks from Yandex.Music to YouTube Music"
    )
    parser.add_argument(
        "--config", 
        type=str, 
        default="config.yaml", 
        help="Config file (default: config/config.yaml)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="tracks.json",
        help="Output json file for transfer results",
    )
    parser.add_argument(
        "--no-proxy", 
        action="store_true", 
        help="Disable proxy (overrides config)"
    )
    parser.add_argument(
        "--proxy-port", 
        type=int, 
        default=1080, 
        help="Proxy port (1080 for ciadpi, 9150 for Tor)"
    )
    parser.add_argument(
        "--log-level", 
        type=str, 
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Specific log file name (optional, default: auto-generated with timestamp)"
    )
    return parser.parse_args()