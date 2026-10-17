import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Union

from . import paths

logger = logging.getLogger(__name__)


def load_config(config_path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """Load configuration from YAML file.

    ``config_path`` defaults to ``config/config.yaml``; a bare file name is
    looked up in ``config/`` before falling back to the legacy repository-root
    location.
    """
    path = paths.resolve_config(config_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            logger.info(f"Config loaded from {path}")
            return config
    except FileNotFoundError:
        logger.error(f"Config file {path} not found!")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing {path}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        raise
