"""Telegram client for the Music app.

Two transports, one API:

* **Bot API** (default) — HTTPS calls to ``api.telegram.org`` using ``requests``.
  Simple and dependency-free, but it needs a network that can reach Telegram.
* **MTProto** (opt-in) — a Telethon client tunnelled through an MTProxy. Use this
  when ``api.telegram.org`` is blocked/unreachable and the only egress is a local
  MTProto proxy (the app's ``tg-ws-proxy`` on ``127.0.0.1:1443``, ``mtg``, …).
  An MTProxy secret is *not* a BotFather token — a bot token is still required,
  the proxy only carries the MTProto stream.

Both transports expose the same methods to the rest of the app:

* **send** — push a message to the configured chat(s) after sync/download work;
* **listen** — run a long-polling (Bot API) or event-driven (MTProto) command
  loop that dispatches incoming commands to the application.

Only users whose id is in the ``allow`` list may run commands; everyone else is
told they are not authorized and their message is ignored.

Configuration comes from the ``telegram:`` section of ``config/config.yaml``
(see ``config/ex_config.yaml``):

* ``token`` (required) — the BotFather token (``TELEGRAM_BOT_TOKEN`` overrides);
* ``chats`` (optional) — chat ids; otherwise the first chat that talks to the
  bot is captured. Chats and the allow-list persist in ``config/telegram.json``;
* Bot API only: ``api_base``, ``proxy`` / ``proxy_url`` (HTTPS/SOCKS proxy);
* MTProto only: ``mtproto: {host, port, secret}`` plus ``api_id`` / ``api_hash``
  from my.telegram.org. The Telethon session lives in
  ``config/telegram_mtproto.session`` (gitignored).

``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_API_ID`` / ``TELEGRAM_API_HASH`` override the
stored values for scripts/tests.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import socket
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from . import paths

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_MTPROXY_HOST = "127.0.0.1"
DEFAULT_MTPROXY_PORT = 1443
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
# For an MTProto-only proxy use `telegram.mtproto` instead (see module docs).
PROXY_URL = "http://127.0.0.1:1443"


class TelegramError(RuntimeError):
    """Raised for Telegram API failures."""


class _State:

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
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _resolve(host: str, port: int, *args, **kwargs):
    """getaddrinfo hook that prepends the known IPv4 address for Telegram."""
    result = _orig_getaddrinfo(host, port, *args, **kwargs)
    if host == API_HOST:
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _proxy_for(config: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Return proxy settings if the config wants an HTTP/SOCKS proxy for Telegram.

    Off by default: the Telegram Bot API works best direct, and the app's
    ``tg-ws-proxy`` on ``1443`` speaks MTProto (see ``_mtproto_for``), not
    HTTPS. Enable it with ``telegram.proxy: true`` and point
    ``telegram.proxy_url`` at a proxy that actually tunnels ``api.telegram.org``.
    """
    proxy = config.get("proxy", False)
    if not proxy:
        return None
    url = config.get("proxy_url", PROXY_URL)
    return {"http": url, "https": url}


def _mtproto_for(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return MTProxy settings when ``telegram.mtproto`` is configured."""
    section = config.get("mtproto") or config.get("mtproxy")
    if not section:
        return None
    if not isinstance(section, dict):
        raise TelegramError("config 'telegram.mtproto' must be a mapping")
    secret = str(section.get("secret") or "").strip()
    if not secret:
        raise TelegramError(
            "telegram.mtproto.secret is required (the proxy secret, not a bot token)"
        )
    return {
        "host": str(section.get("host") or DEFAULT_MTPROXY_HOST),
        "port": _as_int(section.get("port"), DEFAULT_MTPROXY_PORT),
        "secret": secret,
    }


class MTProtoSession:
    """Owns a background asyncio loop and one Telethon client bound to it.

    Telethon binds a client to the loop that is running when it is constructed,
    so the client is created *inside* the loop thread and every coroutine is
    submitted there. One session file = one logged-in account (bot or user).

    ``proxy`` is an optional ``(host, port, secret)`` MTProxy tuple; without it
    Telethon connects to Telegram directly (only works where that is reachable).
    """

    def __init__(
        self,
        session_path: Path,
        api_id: Any,
        api_hash: Any,
        proxy: Optional[tuple] = None,
    ) -> None:
        self.session_path = Path(session_path)
        self.api_id = _as_int(api_id)
        self.api_hash = str(api_hash or "")
        self.proxy = tuple(proxy) if proxy else None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client: Any = None
        self._loop_lock = threading.Lock()

    # ----------------------------------------------------------- loop plumbing
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._loop_main,
                    args=(loop,),
                    name="telegram-mtproto",
                    daemon=True,
                )
                thread.start()
                self._loop, self._thread = loop, thread
        return self._loop

    @staticmethod
    def _loop_main(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro, timeout: Optional[float] = REQUEST_TIMEOUT) -> Any:
        """Run a coroutine on the background loop and wait for its result."""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as e:
            future.cancel()
            raise TelegramError(
                f"Telegram MTProto request timed out after {timeout}s"
            ) from e
        except TelegramError:
            raise
        except Exception as e:
            raise TelegramError(f"Telegram MTProto request failed: {e}") from e

    # ------------------------------------------------------------------ client
    def _make_client(self):
        try:
            from telethon import TelegramClient as _Telethon
            from telethon.network import (
                ConnectionTcpMTProxyRandomizedIntermediate,
            )
        except ImportError as e:
            raise TelegramError(
                "MTProto transport requires the `telethon` package"
            ) from e
        kwargs: Dict[str, Any] = {}
        if self.proxy:
            kwargs["connection"] = ConnectionTcpMTProxyRandomizedIntermediate
            kwargs["proxy"] = self.proxy
        with warnings.catch_warnings():
            # Telethon warns about its python-socks HTTP proxy support; the
            # MTProxy tuple is consumed by the connection class instead.
            warnings.filterwarnings(
                "ignore", message="proxy argument will be ignored.*"
            )
            return _Telethon(
                str(self.session_path), self.api_id, self.api_hash, **kwargs
            )

    async def client(self):
        """Return the connected Telethon client, creating it on first use."""
        if self._client is None:
            self._client = self._make_client()
        if not self._client.is_connected():
            await self._client.connect()
        return self._client

    def connect(self):
        """Ensure the client is connected and return it (blocking)."""
        return self.run(self.client(), timeout=60)

    def close(self) -> None:
        """Disconnect the client (used when throwing a session away)."""
        if self._client is None:
            return
        try:
            self.run(self._client.disconnect(), timeout=10)
        except TelegramError:
            pass
        self._client = None


class TelegramClient:
    """Telegram client: message sending plus a command loop.

    The transport is picked in ``__init__``: ``telegram.mtproto`` selects
    MTProto/Telethon, otherwise the Bot API over ``requests`` is used.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        token_file: Optional[Path] = None,
    ) -> None:
        config = dict(config or {})
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.get("token") or ""
        self.api_base = (config.get("api_base") or DEFAULT_API_BASE).rstrip("/")
        self.api_id = _as_int(os.environ.get("TELEGRAM_API_ID") or config.get("api_id"))
        self.api_hash = str(
            os.environ.get("TELEGRAM_API_HASH") or config.get("api_hash") or ""
        )
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
        self._mtproto = _mtproto_for(config)
        self._proxy = _proxy_for(config)
        self.http = requests.Session()
        if self._proxy:
            self.http.proxies.update(self._proxy)
        # Telethon state: a shared loop+client wrapper plus the client handle.
        # Created lazily so an unconfigured/unused bot makes no network or
        # thread activity at startup.
        self._conn: Optional[MTProtoSession] = (
            MTProtoSession(
                paths.TELEGRAM_SESSION_FILE,
                self.api_id,
                self.api_hash,
                (self._mtproto["host"], self._mtproto["port"], self._mtproto["secret"]),
            )
            if self._mtproto
            else None
        )
        self._tg: Any = None
        self._authorized = False
        self._tg_lock = threading.Lock()

    # ------------------------------------------------------------------ utils
    @property
    def transport(self) -> str:
        """``"mtproto"`` when a proxy is configured, else ``"bot-api"``."""
        return "mtproto" if self._mtproto else "bot-api"

    @property
    def endpoint(self) -> str:
        """Human-readable endpoint description for the CLI status screen."""
        if self._mtproto:
            return f"{self._mtproto['host']}:{self._mtproto['port']}"
        return self.api_base

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

    # ----------------------------------------------------------- MTProto core
    def _run(self, coro, timeout: Optional[float] = REQUEST_TIMEOUT) -> Any:
        """Run a coroutine on the shared background loop (MTProto transport)."""
        return self._conn.run(coro, timeout)

    def _ensure_tg(self):
        """Connect and authenticate the Telethon bot client, then return it."""
        if not self.token:
            raise TelegramError(
                "Telegram token is not configured "
                "(add `telegram.token` to config/config.yaml)"
            )
        if self._conn is None:
            raise TelegramError("MTProto transport is not configured")
        if not self.api_id or not self.api_hash:
            raise TelegramError(
                "MTProto transport needs `telegram.api_id` and "
                "`telegram.api_hash` from my.telegram.org"
            )
        with self._tg_lock:
            client = self._conn.connect()
            if not self._authorized:
                logger.info(
                    "Connecting Telegram MTProto via %s:%s",
                    self._mtproto["host"],
                    self._mtproto["port"],
                )
                if not self._run(client.is_user_authorized(), timeout=30):
                    self._run(client.sign_in(bot_token=self.token), timeout=60)
                self._authorized = True
            self._tg = client
            return client

    def _mtproto_send(self, chat_id: Any, text: str) -> None:
        client = self._ensure_tg()
        payload = text[:4096]
        try:
            peer = int(chat_id)
        except (TypeError, ValueError):
            peer = chat_id

        async def _send() -> None:
            await client.send_message(peer, payload, link_preview=False)

        self._run(_send())

    def _mtproto_me(self) -> Dict[str, Any]:
        client = self._ensure_tg()
        me = self._run(client.get_me())
        return {
            "id": getattr(me, "id", None),
            "username": getattr(me, "username", None),
        }

    # ------------------------------------------------------------------- send
    def send_message(self, chat_id: Any, text: str) -> None:
        """Send a plain-text message to one chat."""
        if self._mtproto:
            self._mtproto_send(chat_id, text)
            return
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
        """Blocking command loop. ``handler`` returns reply text (or None)."""
        if not self.token:
            raise TelegramError("Telegram token is not configured")
        if self._mtproto:
            self._run_mtproto_commands(handler)
            return
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

    def _run_mtproto_commands(
        self,
        handler: Callable[[Dict[str, Any], str], Optional[str]],
    ) -> None:
        """Event-driven command loop for the MTProto transport."""
        try:
            from telethon import events
        except ImportError as e:
            raise TelegramError("MTProto transport requires the `telethon` package") from e
        client = self._ensure_tg()

        async def on_message(event) -> None:
            text = event.raw_text or ""
            if not text:
                return
            chat_id = event.chat_id
            user_id = event.sender_id
            if not self.chats:
                # Keep broadcast() working: remember where the first message came from.
                self.add_chat(chat_id)
                await client.send_message(
                    chat_id,
                    f"✅ Music bot connected. Chat {chat_id} registered — "
                    "you can now send /help",
                )
            if user_id is not None and not self.is_authorized(user_id):
                await client.send_message(
                    chat_id, "You are not authorized to use this bot."
                )
                return
            # The command layer expects a Bot API update shape.
            update = {
                "message": {
                    "chat": {"id": chat_id},
                    "from": {"id": user_id},
                    "text": text,
                }
            }
            # Handlers do blocking work (downloads, transfers) — keep the loop free.
            reply = await asyncio.get_running_loop().run_in_executor(
                None, handler, update, text
            )
            if reply:
                await client.send_message(
                    chat_id, str(reply)[:4096], link_preview=False
                )

        client.add_event_handler(on_message, events.NewMessage(incoming=True))
        logger.info("Telegram MTProto listener started (%s)", self.endpoint)
        try:
            self._run(client.run_until_disconnected(), timeout=None)
        except TelegramError as e:
            logger.warning("Telegram MTProto listener stopped: %s", e)
            raise
        finally:
            try:
                self._run(client.disconnect(), timeout=10)
            except TelegramError:
                pass

    # ----------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        """Summary for the CLI status screen."""
        if not self.token:
            return {
                "configured": False,
                "transport": self.transport,
                "endpoint": self.endpoint,
                "chats": [],
                "allow": [],
                "api_base": self.api_base,
                "proxy": bool(self._proxy),
            }
        info: Dict[str, Any] = {
            "configured": True,
            "transport": self.transport,
            "endpoint": self.endpoint,
            "chats": self.chats,
            "allow": self.allow,
            "api_base": self.api_base,
            "proxy": bool(self._proxy or self._mtproto),
        }
        try:
            me = self._mtproto_me() if self._mtproto else self._call("getMe")
            info["bot_username"] = me.get("username")
            info["bot_id"] = me.get("id")
        except TelegramError as e:
            info["bot_username"] = None
            info["error"] = str(e)
        return info
