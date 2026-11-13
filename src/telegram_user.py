"""Telegram user-account session (MTProto).

A bot account cannot open Saved Messages or enumerate the user's dialogs — those
belong to a real account. This module keeps a **separate** Telethon session
logged in as the user (phone number + login code, plus the two-step password if
one is set), sharing `telegram.api_id` / `api_hash` and the MTProto proxy with
the bot.

Session file: `config/telegram_user.session` (gitignored). The first login is
interactive (CLI prompt); afterwards the authorization is reused until logout.

Usage: Telegram → *User: log in*, then *User: Saved Messages*.
"""

from __future__ import annotations

import asyncio
import getpass
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .telegram import MTProtoSession, TelegramError, _as_int, _mtproto_for

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
MAX_LIMIT = 200


def _describe(me: Any) -> Dict[str, Any]:
    """Flatten a Telethon user object into plain values."""
    name = " ".join(
        p for p in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if p
    )
    return {
        "id": getattr(me, "id", None),
        "username": getattr(me, "username", None),
        "name": name or None,
    }


# Where Telegram said it delivered the login code (SentCode.type).
_CODE_CHANNELS = {
    "SentCodeTypeApp": "in the Telegram app — service chat 'Telegram' (777000)",
    "SentCodeTypeSms": "by SMS",
    "SentCodeTypeCall": "by phone call (the code is spoken)",
    "SentCodeTypeFlashCall": "by flash call (the number is in your call log)",
    "SentCodeTypeMissedCall": "by missed call (last digits of the caller id)",
    "SentCodeTypeFragmentSms": "by SMS via Fragment",
}


def _code_channel(sent: Any) -> str:
    """Human-readable delivery channel from a Telethon ``SentCode``."""
    kind = type(getattr(sent, "type", None)).__name__
    where = _CODE_CHANNELS.get(kind, kind)
    timeout = getattr(sent, "timeout", None)
    suffix = f" (resend allowed after {timeout}s)" if timeout else ""
    return where + suffix


def _flush() -> None:
    """Flush stdout (printing happens from the MTProto loop thread)."""
    import sys

    sys.stdout.flush()


def _print_qr(url: str) -> None:
    """Draw a terminal QR code for the ``tg://login?token=...`` URL."""
    try:
        import sys

        import qrcode
    except ImportError:
        print(f"  Open this URL from a logged-in Telegram app:\n  {url}")
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    sys.stdout.flush()


class TelegramUserClient:
    """One logged-in Telegram *user* account, exposed as blocking methods."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        session_file: Optional[Path] = None,
    ) -> None:
        config = dict(config or {})
        self.api_id = _as_int(os.environ.get("TELEGRAM_API_ID") or config.get("api_id"))
        self.api_hash = str(
            os.environ.get("TELEGRAM_API_HASH") or config.get("api_hash") or ""
        )
        self.phone = str(os.environ.get("TELEGRAM_PHONE") or config.get("phone") or "")
        self._mtproto = _mtproto_for(config)
        self.session_path = Path(session_file or paths.TELEGRAM_USER_SESSION_FILE)
        self._conn = MTProtoSession(
            self.session_path,
            self.api_id,
            self.api_hash,
            (self._mtproto["host"], self._mtproto["port"], self._mtproto["secret"])
            if self._mtproto
            else None,
        )

    # ------------------------------------------------------------------ utils
    @property
    def configured(self) -> bool:
        """True when api_id/api_hash are present (login is still required)."""
        return bool(self.api_id and self.api_hash)

    def _require_credentials(self) -> None:
        if not self.configured:
            raise TelegramError(
                "User session needs `telegram.api_id` and `telegram.api_hash` "
                "(my.telegram.org) in config/config.yaml"
            )

    # ------------------------------------------------------------------- auth
    def is_authorized(self) -> bool:
        """True if the session file holds a logged-in user account."""
        self._require_credentials()

        async def _check() -> bool:
            client = await self._conn.client()
            return bool(await client.is_user_authorized())

        return self._conn.run(_check(), timeout=30)

    def login(
        self, phone: Optional[str] = None, force_sms: bool = False
    ) -> Dict[str, Any]:
        """Interactive login: phone → code (→ 2FA password). Returns the account.

        ``force_sms`` asks Telegram for the code by SMS on the first attempt
        instead of through the app.
        """
        self._require_credentials()
        number = str(phone or self.phone or "").strip()
        if not number:
            number = input("Telegram phone number (+country code): ").strip()
        if not number:
            raise TelegramError("A phone number is required to log in")

        async def _login() -> Dict[str, Any]:
            from telethon.errors import (
                FloodWaitError,
                SendCodeUnavailableError,
                SessionPasswordNeededError,
            )

            client = await self._conn.client()
            if await client.is_user_authorized():
                return _describe(await client.get_me())

            try:
                sent = await client.send_code_request(number, force_sms=force_sms)
            except FloodWaitError as e:
                raise TelegramError(
                    f"Telegram requires a {e.seconds}s wait before sending a code. "
                    "Use the QR login (no code needed) or wait and retry."
                ) from e
            except SendCodeUnavailableError as e:
                raise TelegramError(
                    "Telegram refused another code (all delivery options already "
                    "used). Wait ~10 minutes, or use the QR login (no code needed)."
                ) from e
            print(f"  Login code sent {_code_channel(sent)}")
            loop = asyncio.get_running_loop()
            code = await loop.run_in_executor(
                None,
                lambda: input(
                    "Telegram login code (empty = request an SMS instead): "
                ).strip(),
            )
            if not code:
                try:
                    sent = await client.send_code_request(number, force_sms=True)
                except FloodWaitError as e:
                    raise TelegramError(
                        f"Telegram requires a {e.seconds}s wait before an SMS. "
                        "Use the QR login instead."
                    ) from e
                except SendCodeUnavailableError as e:
                    raise TelegramError(
                        "Telegram refused the SMS too (all delivery options used). "
                        "Use the QR login instead."
                    ) from e
                print(f"  Code re-sent {_code_channel(sent)}")
                code = await loop.run_in_executor(
                    None, lambda: input("Telegram login code: ").strip()
                )
            try:
                await client.sign_in(phone=number, code=code)
            except SessionPasswordNeededError:
                pwd = await loop.run_in_executor(
                    None, lambda: getpass.getpass("Two-step verification password: ")
                )
                await client.sign_in(password=pwd)
            return _describe(await client.get_me())

        me = self._conn.run(_login(), timeout=300)
        self.phone = number
        logger.info("Telegram user session logged in as %s", me.get("id"))
        return me

    def login_qr(self, timeout: float = 180, attempts: int = 2) -> Dict[str, Any]:
        """Log in by scanning a QR code (no code delivery, no SMS limits).

        Scan it with Telegram on the phone: **Settings → Devices → Link Desktop
        Device** (the phone then asks you to confirm the login — accept it).
        Expired QRs are regenerated automatically. If two-step verification is
        enabled, the password is asked afterwards.
        """
        self._require_credentials()

        async def _login() -> Dict[str, Any]:
            from telethon import events
            from telethon.errors import SessionPasswordNeededError
            from telethon.tl import types as tl_types

            client = await self._conn.client()
            if await client.is_user_authorized():
                return _describe(await client.get_me())

            loop = asyncio.get_running_loop()
            password_done = False

            async def _sign_in_password() -> None:
                nonlocal password_done
                pwd = await loop.run_in_executor(
                    None, lambda: getpass.getpass("Two-step verification password: ")
                )
                await client.sign_in(password=pwd)
                password_done = True

            for attempt in range(1, attempts + 1):
                qr = await client.qr_login()
                print(
                    "\n  Scan with Telegram → Settings → Devices → "
                    "Link Desktop Device:\n"
                )
                _print_qr(qr.url)
                print(
                    f"\n  Or send this link to yourself in Telegram and tap it:\n"
                    f"  {qr.url}"
                )
                if getattr(qr, "expires", None):
                    print(f"  QR #{attempt} expires at {qr.expires:%H:%M:%S}.")
                print(f"  Waiting up to {int(timeout)}s — scan, then CONFIRM on the phone…")
                _flush()

                # Progress feedback: Telegram pushes UpdateLoginToken once the
                # scanning device accepts the token.
                async def _on_token_update(_update) -> None:
                    print("  ✅ QR accepted by the phone — finishing login…")
                    _flush()

                client.add_event_handler(
                    _on_token_update, events.Raw(tl_types.UpdateLoginToken)
                )
                try:
                    await qr.wait(timeout)
                except SessionPasswordNeededError:
                    # The account has two-step verification: the QR import is
                    # accepted but the login must be completed with the password.
                    print("  Two-step verification enabled — password required.")
                    _flush()
                    await _sign_in_password()
                    break
                except asyncio.TimeoutError:
                    logger.info("QR login attempt %s timed out", attempt)
                    if attempt >= attempts:
                        raise TelegramError(
                            "QR login timed out — the scan was not confirmed. "
                            "Run it again for a fresh QR code."
                        )
                    print("  QR expired/not confirmed — generating a new one…")
                    continue
                except Exception as e:  # auth errors surface here
                    raise TelegramError(f"QR login failed: {e}") from e
                finally:
                    client.remove_event_handler(_on_token_update)
                break

            if not await client.is_user_authorized() and not password_done:
                await _sign_in_password()
            return _describe(await client.get_me())

        me = self._conn.run(_login(), timeout=timeout * attempts + 90)
        logger.info("Telegram user session logged in via QR as %s", me.get("id"))
        return me

    def logout(self) -> None:
        """Terminate the session on Telegram's side and delete the local file."""
        try:
            async def _logout() -> None:
                client = await self._conn.client()
                if await client.is_user_authorized():
                    await client.log_out()

            self._conn.run(_logout(), timeout=30)
        except TelegramError as e:
            logger.warning("Telegram user logout failed: %s", e)
        finally:
            self._conn.close()
            for suffix in ("", "-journal", "-wal", "-shm"):
                try:
                    Path(str(self.session_path) + suffix).unlink()
                except FileNotFoundError:
                    pass

    # ----------------------------------------------------------------- data
    def get_saved_messages(
        self, limit: int = DEFAULT_LIMIT, offset_id: int = 0
    ) -> List[Dict[str, Any]]:
        """Return the newest messages of Saved Messages, newest first.

        Each row is ``{id, date, text, media, out}``. ``offset_id`` pages back:
        pass the ``id`` of the last row you already have.
        """
        self._require_credentials()
        try:
            count = int(limit or DEFAULT_LIMIT)
        except (TypeError, ValueError):
            count = DEFAULT_LIMIT
        count = max(1, min(count, MAX_LIMIT))

        async def _fetch() -> List[Dict[str, Any]]:
            client = await self._conn.client()
            if not await client.is_user_authorized():
                raise TelegramError(
                    "Telegram user account is not logged in — "
                    "run Telegram → User: log in"
                )
            messages = await client.get_messages(
                "me", limit=count, offset_id=int(offset_id or 0)
            )
            return [
                {
                    "id": m.id,
                    "date": m.date.strftime("%Y-%m-%d %H:%M") if m.date else "",
                    "text": m.message or "",
                    "media": type(m.media).__name__ if m.media else None,
                    "out": bool(m.out),
                }
                for m in messages
            ]

        return self._conn.run(_fetch(), timeout=60)

    # --------------------------------------------------------------- status
    def status(self) -> Dict[str, Any]:
        """Summary for the CLI status screen (never raises)."""
        info: Dict[str, Any] = {
            "configured": self.configured,
            "session": str(self.session_path),
            "phone": self.phone,
            "authorized": False,
        }
        if not self.configured:
            info["error"] = "telegram.api_id / api_hash are not configured"
            return info
        try:
            info["authorized"] = self.is_authorized()
            if info["authorized"]:
                async def _me() -> Dict[str, Any]:
                    client = await self._conn.client()
                    return _describe(await client.get_me())

                info.update(self._conn.run(_me(), timeout=30))
        except TelegramError as e:
            info["error"] = str(e)
        return info
