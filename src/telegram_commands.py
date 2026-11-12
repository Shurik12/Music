"""Telegram command handlers for the Music app.

Maps incoming Telegram commands to the same client methods the curses CLI uses,
so the bot becomes a remote control for the app. ``create_handler`` builds a
closure over the live clients and returns the callable the ``TelegramClient``
poll loop expects: ``handler(update, text) -> Optional[str]`` (reply text, or
None to send nothing).

Commands run on the polling thread. Long operations (downloads, transfers)
block the loop — by design for a personal single-user bot; each command sends a
start message and a result message back to the chat.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from .buildin_maps import MapSyncError, export_maps
from .telegram import TelegramClient


class _TelegramDispatch:
    """Bundles the clients plus a way to send progress/result messages to a chat."""

    def __init__(
        self,
        yamusic: Any,
        ytmusic: Any,
        buildin: Any,
        tg: TelegramClient,
    ) -> None:
        self.yamusic = yamusic
        self.ytmusic = ytmusic
        self.buildin = buildin
        self.tg = tg

    # ------------------------------------------------------------------ send
    def _to_chat(self, chat_id: Any, text: str) -> None:
        self.tg.send_message(chat_id, text)

    def _chat_of(self, update: Dict[str, Any]) -> Any:
        return update["message"]["chat"]["id"]

    # ---------------------------------------------------------------- commands
    def cmd_help(self, update: Dict[str, Any]) -> str:
        return (
            "Music bot commands\n"
            "\n"
            "• /help — this message\n"
            "• /status — bot + library summary\n"
            "• /playlists — list YouTube Music playlists\n"
            "• /ya — list Yandex Music playlists\n"
            "• /transfer — liked tracks: Yandex → YouTube (destructive, slow)\n"
            "• /download — download all YouTube playlists (slow)\n"
            "• /yadownload — download all Yandex playlists (slow)\n"
            "• /liked — download Yandex liked tracks (slow)\n"
            "• /maps — export playlist maps to Buildin\n"
            "• /notify <text> — broadcast a message to all chats\n"
        )

    def cmd_status(self, update: Dict[str, Any]) -> str:
        info = self.tg.status()
        lines = [
            f"🤖 Bot: @{info.get('bot_username') or 'unknown'}",
            f"  chats: {len(info['chats'])}   allowed users: "
            f"{info['allow'] if info['allow'] else 'anyone (open)'}",
            f"  proxy: {'on' if info['proxy'] else 'off'}",
        ]
        try:
            yt = self.ytmusic.get_playlists()
            lines.append(f"🎵 YouTube Music playlists: {len(yt)}")
        except Exception as e:
            lines.append(f"🎵 YouTube Music: {e}")
        try:
            ya = self.yamusic.get_playlists()
            lines.append(f"🎵 Yandex Music playlists: {len(ya)}")
        except Exception as e:
            lines.append(f"🎵 Yandex Music: {e}")
        return "\n".join(lines)

    def cmd_playlists(self, update: Dict[str, Any]) -> str:
        try:
            playlists = self.ytmusic.get_playlists()
        except Exception as e:
            return f"❌ Error listing playlists: {e}"
        if not playlists:
            return "No YouTube Music playlists found."
        lines = [f"🎵 {len(playlists)} YouTube Music playlists:"]
        for p in playlists:
            lines.append(f"  • {p['title']}  ({p['playlistId']})")
        return "\n".join(lines[:40])

    def cmd_ya(self, update: Dict[str, Any]) -> str:
        try:
            playlists = self.yamusic.get_playlists()
        except Exception as e:
            return f"❌ Error listing Yandex playlists: {e}"
        if not playlists:
            return "No Yandex Music playlists found."
        lines = [f"🎵 {len(playlists)} Yandex Music playlists:"]
        for p in playlists:
            lines.append(f"  • {p.title}")
        return "\n".join(lines[:40])

    def cmd_transfer(self, update: Dict[str, Any]) -> str:
        chat_id = self._chat_of(update)
        self._to_chat(chat_id, "🚀 Starting transfer: Yandex liked → YouTube Music…")
        start = time.time()
        try:
            tracks = self.yamusic.export_liked_tracks()
            tracks.reverse()
            not_found, errors = self.ytmusic.import_liked_tracks(tracks)
            elapsed = int(time.time() - start)
            ok = len(tracks) - len(not_found) - len(errors)
            lines = [
                f"✅ Transfer finished in {elapsed}s",
                f"  total: {len(tracks)}",
                f"  imported: {ok}",
                f"  not found: {len(not_found)}",
                f"  errors: {len(errors)}",
            ]
            for t in (not_found or [])[:5]:
                lines.append(f"  ⚠️ not found: {t.artist} - {t.name}")
            for t in (errors or [])[:5]:
                lines.append(f"  ❌ error: {t.artist} - {t.name}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Transfer failed: {e}"

    def cmd_download(self, update: Dict[str, Any]) -> str:
        chat_id = self._chat_of(update)
        self._to_chat(chat_id, "⬇️ Downloading all YouTube Music playlists… (long)")
        start = time.time()
        try:
            self.ytmusic.download_all_playlists()
            return f"✅ YouTube Music download finished in {int(time.time() - start)}s"
        except Exception as e:
            return f"❌ Download failed: {e}"

    def cmd_yadownload(self, update: Dict[str, Any]) -> str:
        chat_id = self._chat_of(update)
        self._to_chat(chat_id, "⬇️ Downloading all Yandex Music playlists… (long)")
        start = time.time()
        try:
            self.yamusic.download_playlists()
            return f"✅ Yandex Music download finished in {int(time.time() - start)}s"
        except Exception as e:
            return f"❌ Download failed: {e}"

    def cmd_liked(self, update: Dict[str, Any]) -> str:
        chat_id = self._chat_of(update)
        self._to_chat(chat_id, "⬇️ Downloading Yandex liked tracks… (long)")
        start = time.time()
        try:
            self.yamusic.download_like_tracks()
            return f"✅ Yandex liked download finished in {int(time.time() - start)}s"
        except Exception as e:
            return f"❌ Download failed: {e}"

    def cmd_maps(self, update: Dict[str, Any]) -> str:
        chat_id = self._chat_of(update)
        self._to_chat(chat_id, "🗺️ Exporting playlist maps to Buildin…")
        try:
            result = export_maps(self.buildin)
        except MapSyncError as e:
            return f"❌ Buildin export failed: {e}"
        except Exception as e:
            return f"❌ Buildin export failed: {type(e).__name__}: {e}"
        return (
            "✅ Maps exported to Buildin\n"
            f"  page: {result['page_id']}\n"
            f"  database: {result['database_id']}\n"
            f"  {result['created']} created, {result['updated']} updated, "
            f"{result['unchanged']} unchanged (total {result['total']})"
        )

    def cmd_notify(self, update: Dict[str, Any], text: str) -> str:
        # Text after the command (already stripped of the command word).
        body = text.strip()
        if not body:
            return "Usage: /notify <message>"
        sent = self.tg.broadcast(body)
        return f"📣 Sent to {sent} chat(s)"

    # -------------------------------------------------------------- dispatch
    def dispatch(self, update: Dict[str, Any], text: str) -> Optional[str]:
        """Route ``text`` to a command. Returns reply text or None."""
        if not text.startswith("/"):
            return None
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@", 1)[0].lower()  # strip @botname suffix
        arg = parts[1] if len(parts) > 1 else ""

        simple: Dict[str, Callable[[Dict[str, Any]], str]] = {
            "/help": self.cmd_help,
            "/status": self.cmd_status,
            "/playlists": self.cmd_playlists,
            "/ya": self.cmd_ya,
            "/transfer": self.cmd_transfer,
            "/download": self.cmd_download,
            "/yadownload": self.cmd_yadownload,
            "/liked": self.cmd_liked,
            "/maps": self.cmd_maps,
        }
        if cmd in simple:
            return simple[cmd](update)
        if cmd == "/notify":
            return self.cmd_notify(update, arg)
        return f"Unknown command: {cmd}. Send /help for the list."


def create_handler(yamusic: Any, ytmusic: Any, buildin: Any,
                   tg: TelegramClient) -> Callable[[Dict[str, Any], str], Optional[str]]:
    """Build the ``TelegramClient.run_commands`` handler for the app's clients."""
    dispatch = _TelegramDispatch(yamusic, ytmusic, buildin, tg)
    return lambda update, text: dispatch.dispatch(update, text)
