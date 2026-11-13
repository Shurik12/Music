"""Config maintenance helpers.

Run as a module::

    uv run python -m src.config_tools inline-browser

``inline-browser`` merges the YouTube Music browser headers from
``config/browser.json`` into ``config/config.yaml`` under ``ytmusic.auth``, so a
single gitignored file holds all credentials. The section is written as a
managed, marker-delimited block (see :func:`src.config.update_section`), so a
re-export replaces it in place and the rest of the file keeps its comments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from . import paths
from .config import update_section


def _load_headers(browser_file: Path) -> Dict[str, Any]:
    try:
        headers = json.loads(Path(browser_file).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SystemExit(
            f"{browser_file} not found — export it first (ytmusicapi browser)"
        ) from e
    except json.JSONDecodeError as e:
        raise SystemExit(f"{browser_file} is not valid JSON: {e}") from e
    if not isinstance(headers, dict) or not headers:
        raise SystemExit(f"{browser_file} does not contain a headers object")
    keys = {str(k).lower() for k in headers}
    if "cookie" not in keys or "authorization" not in keys:
        raise SystemExit(
            f"{browser_file} lacks 'cookie'/'authorization' headers — re-export it "
            "with 'Copy as fetch (Node.js)'"
        )
    return headers


def inline_browser(config_file: Path, browser_file: Path) -> int:
    """Write ``browser_file`` into ``config_file`` as ``ytmusic.auth``.

    Other keys of an existing ``ytmusic:`` section are preserved. Returns the
    number of headers written.
    """
    config_file, browser_file = Path(config_file), Path(browser_file)
    headers = _load_headers(browser_file)

    section: Dict[str, Any] = {}
    try:
        config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        config = {}
    if isinstance(config, dict) and isinstance(config.get("ytmusic"), dict):
        section = dict(config["ytmusic"])
    section["auth"] = headers

    update_section(config_file, "ytmusic", section)
    return len(headers)


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.config_tools",
        description="Maintenance helpers for config/config.yaml",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inline = sub.add_parser(
        "inline-browser",
        help="merge config/browser.json into config.yaml as ytmusic.auth",
    )
    inline.add_argument(
        "--config",
        default=None,
        help="target config (default: config/config.yaml)",
    )
    inline.add_argument(
        "--browser",
        default=None,
        help="browser auth JSON (default: config/browser.json)",
    )

    args = parser.parse_args(argv)
    if args.command == "inline-browser":
        config_file = paths.resolve_config(args.config)
        browser_file = Path(args.browser) if args.browser else paths.browser_auth_file()
        count = inline_browser(config_file, browser_file)
        print(f"Merged {count} headers into {config_file} (ytmusic.auth).")
        print("You can now delete config/browser.json, or keep it as a fallback.")


if __name__ == "__main__":
    main()
