"""Telegram Bot API client.

Self-contained: it only uses ``requests`` (already a project dependency), so no
extra library is needed. It covers the two things this app wants from Telegram:

* **send** — push a message to the configured chat(s) after sync/download work;
* **listen** — run a long-polling command loop that dispatches incoming
  commands to the application and reports the results back to the chat.

Only users whose id is in the ``allow`` list may run commands; everyone else is
told they are not authorized and their message is ignored.

Configuration comes from the ``telegram:`` section of ``config/config.yaml``
(see ``config/ex_config.yaml``): ``token`` (required, the BotFather token) and
``chats`` (a list of chat ids, optional — if omitted, the poller auto-captures
the first chat that talks to the bot). ``chats`` and the captured id are
persisted in ``config/telegram.json`` (gitignored).

The Bot API endpoint defaults to ``https://api.telegram.org``. When a SOCKS5
proxy is configured (see ``_proxy_for``) the session routes through it, matching
the rest of the app's networking; set ``api_base`` in config to override.

``TELEGRAM_BOT_TOKEN`` overrides the stored token for scripts/tests.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from . import paths

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 30
POLL_TIMEOUT = 30
# Some networks resolve api.telegram.org to IPv6 only (no IPv6 route), which
# breaks direct and SOCKS5 connections. A known-good IPv4 fallback lets the
# client force an IPv4 connection when the host's A record is unreachable.
API_TELEGRAM_IPV4 = "149.154.166.110"
API_HOST = "api.telegram.org"
# Local proxy for Telegram only (the Bot API also works directly — set
# `telegram.proxy: false` to bypass). This is the app's HTTP CONNECT proxy
# (tg-ws-proxy); it tunnels HTTPS, so use an `http://` scheme. Override with
# `telegram.proxy_url` in config if you point at a SOCKS5 proxy instead.
PROXY_URL = "http://127.0.0.1:1443"


class TelegramError(RuntimeError):
    """Raised for Telegram API failures."""


class _State:
    """Small JSON state file (chat allow-list) with owner-only permissions."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise TelegramError(f"Corrupt Telegram state file {self.path}: {e}") from e

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)


def _resolve(host: str, port: int, family: int = 0, type: int = 0,
             proto: int = 0, flags: int = 0) -> List[tuple]:
    """Resolve a host, preferring IPv4.

    Mirrors ``socket.getaddrinfo`` (accepts 2–6 args). Returns the normal
    result, but for the Telegram API host — if it resolves to IPv6 only (no
    IPv4 route on the network) — it prepends a known-good IPv4 address so the
    connection can go down the working IPv4 path (direct mode).
    """
    try:
        result = _orig_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        return []
    has_ipv4 = any(family_ == socket.AF_INET for family_, *_ in result)
    if (not has_ipv4) and (host in (API_HOST, API_TELEGRAM_IPV4)):
        try:
            result = _orig_getaddrinfo(
                API_TELEGRAM_IPV4, port, socket.AF_INET, socket.SOCK_STREAM
            ) + result
        except socket.gaierror:
            pass
    return result


# Force our resolver for Telegram API connections (requests uses the global
# getaddrinfo via urllib3). Installed once, cheap for other hosts.
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = _resolve


def _proxy_for(config: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Return proxy settings if the config wants a proxy for Telegram.

    Off by default: the Telegram Bot API works best direct, and the app's
    ``tg-ws-proxy`` on ``1443`` is Telegram-app-only (it does not serve the
    Bot API over HTTPS). Enable it with ``telegram.proxy: true`` and point
    ``telegram.proxy_url`` at a proxy that actually tunnels ``api.telegram.org``.
    """
    proxy = config.get("proxy", False)
    if not proxy:
        return None
    url = config.get("proxy_url", PROXY_URL)
    return {"http": url, "https": url}


class TelegramClient:
    """Minimal Bot API client: message sending plus a long-poll command loop."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        token_file: Optional[Path] = None,
    ) -> None:
        config = dict(config or {})
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("token") or ""
        self.api_base = (config.get("api_base") or DEFAULT_API_BASE).rstrip("/")
        self.chats: List[Any] = list(config.get("chats") or [])
        self.allow: List[int] = []
        self.state = _State(token_file or paths.TELEGRAM_STATE_FILE)
        # Merge persisted state on top: an auto-captured chat or allow-list set
        # previously should stick, but an empty/absent state must not wipe
        # config-provided chats (fresh start).
        stored = self.state.load()
        if stored.get("chats"):
            self.chats = list(stored["chats"])
        if stored.get("allow"):
            self.allow = list(stored["allow"])
        self._proxy = _proxy_for(config)
        self.http = requests.Session()
        if self._proxy:
            self.http.proxies.update(self._proxy)

    # ------------------------------------------------------------------ utils
    def _url(self, method: str) -> str:
        if not self.token:
            raise TelegramError(
                "Telegram token is not configured "
                "(add `telegram.token` to config/config.yaml)"
            )
        return f"{self.api_base}/bot{self.token}/{method}"

    def _call(self, method: str, **params: Any) -> Any:
        """Call a Bot API method and return the ``result`` payload."""
        last_error = ""
        try:
            resp = self.http.post(
                self._url(method), data=params, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise TelegramError(f"Telegram {method} request failed: {e}") from e

        if resp.status_code == 429:
            # Rate-limited: honour the server's suggested wait and retry once.
            retry = resp.json().get("parameters", {}).get("retry_after", 3)
            time.sleep(retry + 1)
            resp = self.http.post(
                self._url(method), data=params, timeout=REQUEST_TIMEOUT
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise TelegramError(f"Telegram {method}: bad response body") from e

        if not data.get("ok"):
            desc = data.get("description", "")
            code = data.get("error_code")
            last_error = f"{code}: {desc}" if code else desc
            if code == 429:
                retry = data.get("parameters", {}).get("retry_after", 3)
                time.sleep(retry + 1)
                resp = self.http.post(
                    self._url(method), data=params, timeout=REQUEST_TIMEOUT
                )
                data = resp.json()
                if not data.get("ok"):
                    raise TelegramError(f"Telegram {method} failed: {data.get('description')}")
            else:
                raise TelegramError(f"Telegram {method} failed: {last_error}")
        return data.get("result")

    # ------------------------------------------------------------------- send
    def send_message(self, chat_id: Any, text: str) -> None:
        """Send a plain-text message to one chat."""
        self._call(
            "sendMessage",
            chat_id=chat_id,
            text=text[:4096],
            disable_web_page_preview=True,
        )

    def broadcast(self, text: str) -> int:
        """Send ``text`` to every known chat. Returns the number of chats hit."""
        sent = 0
        for chat in self.chats:
            try:
                self.send_message(chat, text)
                sent += 1
            except TelegramError as e:
                logger.warning("Telegram send to %s failed: %s", chat, e)
        return sent

    # ------------------------------------------------------------------ state
    def is_authorized(self, user_id: int) -> bool:
        """True if the allow-list is empty (open) or contains ``user_id``."""
        return not self.allow or int(user_id) in self.allow

    def add_chat(self, chat_id: Any) -> None:
        """Record a chat id (auto-capture on first contact)."""
        if chat_id not in self.chats:
            self.chats.append(chat_id)
            self.state.save({"chats": self.chats, "allow": self.allow})

    def set_allow(self, ids: List[int]) -> None:
        """Set the allowed user ids and persist."""
        self.allow = list(ids)
        self.state.save({"chats": self.chats, "allow": self.allow})

    # ------------------------------------------------------------------ listen
    def _get_updates(self, offset: int,
                     handler: Callable[[Dict[str, Any]], Optional[str]]) -> int:
        """Pull one batch of updates, dispatch each, return the next offset."""
        result = self._call(
            "getUpdates",
            offset=offset,
            timeout=POLL_TIMEOUT,
            allowed_updates=["message"],
        )
        for update in result or []:
            offset = update["update_id"] + 1
            update.setdefault("message", {}).setdefault("text", None)
            text = update["message"]["text"]
            if text is None:
                continue
            chat = update["message"]["chat"]
            user = update["message"].get("from", {})
            user_id = user.get("id")
            from_id = user_id
            if from_id is not None and not self.is_authorized(from_id):
                self.send_message(chat["id"], "You are not authorized to use this bot.")
                continue
            reply = handler(update, text)
            if reply:
                self.send_message(chat["id"], reply)
        return offset

    def run_commands(
        self,
        handler: Callable[[Dict[str, Any], str], Optional[str]],
    ) -> None:
        """Blocking long-poll loop. ``handler`` returns reply text (or None)."""
        if not self.token:
            raise TelegramError("Telegram token is not configured")
        # If no chat is known yet, capture the first one that contacts us so
        # broadcast() has somewhere to send.
        if not self.chats:
            self._capture_first_chat()

        offset = 0
        while True:
            try:
                offset = self._get_updates(offset, handler)
            except KeyboardInterrupt:
                logger.info("Telegram poll loop stopped by user")
                return
            except TelegramError as e:
                # Transient failures (network, 502 from Telegram, proxy down)
                # should not kill the loop — back off and retry.
                logger.warning("Telegram poll error: %s (retrying in 3s)", e)
                time.sleep(3)

    def _capture_first_chat(self) -> None:
        """Wait for the first message so a chat id is known for broadcasting."""
        logger.info("No Telegram chat configured; waiting for the first message...")
        try:
            result = self._call("getUpdates", offset=0, timeout=10,
                                allowed_updates=["message"])
        except TelegramError as e:
            logger.warning("Could not capture first Telegram chat: %s", e)
            return
        for update in result or []:
            chat = update.get("message", {}).get("chat")
            if chat and chat["id"] not in self.chats:
                self.add_chat(chat["id"])
                self.send_message(
                    chat["id"],
                    f"✅ Music bot connected. Chat {chat['id']} registered — "
                    "you can now send /help",
                )
                break

    # ----------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        """Summary for the CLI status screen."""
        if not self.token:
            return {
                "configured": False,
                "chats": [],
                "allow": [],
                "api_base": self.api_base,
                "proxy": bool(self._proxy),
            }
        info: Dict[str, Any] = {
            "configured": True,
            "chats": self.chats,
            "allow": self.allow,
            "api_base": self.api_base,
            "proxy": bool(self._proxy),
        }
        try:
            me = self._call("getMe")
            info["bot_username"] = me.get("username")
            info["bot_id"] = me.get("id")
        except TelegramError as e:
            info["bot_username"] = None
            info["error"] = str(e)
        return info
