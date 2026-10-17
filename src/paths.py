"""Filesystem layout for the project.

Every runtime path is anchored to the repository root (the parent of ``src/``)
so the CLI behaves the same no matter which directory it is launched from.

Layout::

    config/     user-supplied configuration and secrets
    data/       live state rewritten by the app (playlist maps)
    downloads/  downloaded tracks
    logs/       logs and generated reports

``config.yaml`` and ``browser.json`` are gitignored user files; older checkouts
may still keep them in the repository root, so :func:`resolve_config` and
:func:`browser_auth_file` fall back to those legacy locations with a warning.
"""

from pathlib import Path
from typing import Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
DOWNLOAD_DIR = PROJECT_ROOT / "downloads"
LOGS_DIR = PROJECT_ROOT / "logs"

DEFAULT_CONFIG_FILE = CONFIG_DIR / "config.yaml"
EXAMPLE_CONFIG_FILE = CONFIG_DIR / "ex_config.yaml"
BROWSER_AUTH_FILE = CONFIG_DIR / "browser.json"
BUILDIN_TOKENS_FILE = CONFIG_DIR / "buildin_tokens.json"
PLAYLISTS_MAP_FILE = DATA_DIR / "playlists_map.yaml"
YAMUSIC_MAP_FILE = DATA_DIR / "yamusic.yaml"

PathLike = Union[str, Path]


def ensure_directories() -> None:
    """Create the directories the app reads from or writes to."""
    for directory in (CONFIG_DIR, DATA_DIR, DOWNLOAD_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def resolve(path: PathLike) -> Path:
    """Resolve a user-supplied path against the repository root.

    Absolute and ``~``-relative paths are returned unchanged; anything else is
    interpreted relative to the repository root instead of the current working
    directory.
    """
    resolved = Path(path).expanduser()
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


def _with_legacy(primary: Path, legacy_name: str) -> Path:
    """Return ``primary`` unless it is missing and a legacy root file exists."""
    if primary.exists():
        return primary
    legacy = PROJECT_ROOT / legacy_name
    if legacy.exists():
        print(
            f"WARNING: using legacy {legacy_name} in the repository root; "
            f"move it to {primary.relative_to(PROJECT_ROOT)}"
        )
        return legacy
    return primary


def resolve_config(value: Union[PathLike, None] = None) -> Path:
    """Locate the Yandex Music config file.

    A bare file name (the ``--config`` default) is looked up in ``config/``
    first and then in the repository root for compatibility with the old
    layout. An explicit path is used as given.
    """
    if value is None:
        return _with_legacy(DEFAULT_CONFIG_FILE, "config.yaml")

    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if len(path.parts) == 1:
        return _with_legacy(CONFIG_DIR / path, path.name)
    return PROJECT_ROOT / path


def browser_auth_file() -> Path:
    """Return the YouTube Music browser auth file (``config/browser.json``)."""
    return _with_legacy(BROWSER_AUTH_FILE, "browser.json")
