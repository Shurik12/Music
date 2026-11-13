import yaml
import logging
import os
from pathlib import Path
from typing import Dict, Any, Union

from . import paths

logger = logging.getLogger(__name__)

# Managed sections are delimited by these markers so the app can rewrite only
# its own block and keep the rest of the user's file (comments included).
_MARK_START = "# >>> {key} (managed by the app — do not edit inside) >>>"
_MARK_END = "# <<< {key} <<<"


def _render_block(key: str, value: Dict[str, Any]) -> str:
    body = yaml.safe_dump(
        {key: value},
        sort_keys=False,
        allow_unicode=True,
        width=10**9,
        default_flow_style=False,
    )
    return _MARK_START.format(key=key) + "\n" + body + _MARK_END.format(key=key) + "\n"


def update_section(
    config_path: Union[str, Path], key: str, value: Dict[str, Any]
) -> None:
    """Write the top-level ``key`` section of a YAML config, preserving the rest.

    The section is written between marker comments and replaced in place on the
    next call. Raises ``ValueError`` if a hand-written ``key`` section exists
    without the markers (the caller must remove it first).
    """
    path = paths.resolve(config_path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = _render_block(key, value) if value else ""
    start_marker = _MARK_START.format(key=key)
    end_marker = _MARK_END.format(key=key)

    if start_marker in text:
        start = text.index(start_marker)
        end = text.index(end_marker, start) + len(end_marker)
        if text[end:end + 1] == "\n":
            end += 1
        new_text = text[:start] + block + text[end:]
    else:
        parsed = yaml.safe_load(text) or {}
        if isinstance(parsed, dict) and key in parsed:
            raise ValueError(
                f"{path} already contains a hand-written '{key}:' section; "
                "remove it and let the app manage it"
            )
        separator = "\n\n" if text.strip() else ""
        new_text = text.rstrip("\n") + separator + block

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


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
