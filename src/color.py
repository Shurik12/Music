"""Terminal color helpers (ANSI escape codes, no dependencies).

Disable by setting ``NO_COLOR=1`` or ``TERM=dumb`` in the environment.
"""

from __future__ import annotations
import os

_enabled = os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"

# --- ANSI code pairs (open, close) ---
_B = "\x1b[1m"   # bold
_R = "\x1b[0m"   # reset

_CYAN     = ("\x1b[96m", _R)
_GREEN    = ("\x1b[92m", _R)
_YELLOW   = ("\x1b[93m", _R)
_RED      = ("\x1b[91m", _R)
_BLUE     = ("\x1b[94m", _R)
_MAGENTA  = ("\x1b[95m", _R)
_CYAN_B   = (_B + "\x1b[96m", _R)
_GREEN_B  = (_B + "\x1b[92m", _R)
_YELLOW_B = (_B + "\x1b[93m", _R)
_RED_B    = (_B + "\x1b[91m", _R)


def _wrap(text: str, pair: tuple[str, str]) -> str:
    if not _enabled:
        return text
    open_c, close_c = pair
    return f"{open_c}{text}{close_c}"


def bold(text: str) -> str:
    return _wrap(text, (_B, _R))


def cyan(text: str) -> str:
    return _wrap(text, _CYAN)


def green(text: str) -> str:
    return _wrap(text, _GREEN)


def yellow(text: str) -> str:
    return _wrap(text, _YELLOW)


def red(text: str) -> str:
    return _wrap(text, _RED)


def blue(text: str) -> str:
    return _wrap(text, _BLUE)


def magenta(text: str) -> str:
    return _wrap(text, _MAGENTA)


def cyan_bold(text: str) -> str:
    return _wrap(text, _CYAN_B)


def green_bold(text: str) -> str:
    return _wrap(text, _GREEN_B)


def yellow_bold(text: str) -> str:
    return _wrap(text, _YELLOW_B)


def red_bold(text: str) -> str:
    return _wrap(text, _RED_B)
