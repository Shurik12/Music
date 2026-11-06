import logging
from datetime import datetime
from typing import Optional

from . import paths


def setup_logging(log_level: str = "INFO", output_file: Optional[str] = None) -> None:
    """Setup logging to file only (no console output)."""
    log_dir = paths.LOGS_DIR
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"music_api_{timestamp}.log"

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    logger.info("Logging initialized. Log file: %s", log_file)
    if output_file:
        logger.info("Output file for results: %s", output_file)
    
    
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a specific module"""
    return logging.getLogger(name)