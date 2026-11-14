"""Yandex Disk REST API client.

Self-contained (only ``requests``) so no Yandex SDK is required. Talks to the
official REST API at ``https://api.yandex.net/disk/``, authenticating with a
Yandex OAuth access token that is auto-refreshed and persisted in
``config/config.yaml`` under the managed ``yandex_disk.auth`` block.

Login (``YandexDiskClient.login``) asks for a **Yandex OAuth access token** to
paste — either one you obtain at developer.yandex.com, or the same general
Yandex token you already use as ``yamusic_token`` (the Disk API accepts the
same token family). The pasted token is stored in ``config/config.yaml`` under
``yandex_disk.auth`` and (if it also carries a ``refresh_token``)
auto-refreshed.

The OAuth **device flow** and **authorization-code flow** (a local
``127.0.0.1`` callback) both fail with this public client: Yandex treats it as a
*registered* app, so ``/device/code`` rejects a custom scope
(``invalid_scope: err_scope not empty``) and ``/authorize`` rejects any
``redirect_uri`` other than its own fixed callback
(``redirect_uri не совпадает с Callback URL``). Getting a token therefore
requires the developer.yandex.com page or reusing a Yandex token you already
hold.

Set ``YANDEX_DISK_TOKEN`` to bypass the stored token (useful for scripts/tests).
All file operations are best-effort: network/permission errors are logged and
reported as ``None``/empty rather than aborting a batch, matching how the rest
of the app treats downloads.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from . import paths
from .color import cyan, green
from .config import update_section

logger = logging.getLogger(__name__)

API_BASE = "https://api.yandex.net/disk"
OAUTH_BASE = "https://oauth.yandex.ru"
TOKEN_ENDPOINT = f"{OAUTH_BASE}/token"

# Public OAuth client of the official Yandex.Music Android app — the same
# credentials the yandex-music library uses. It is only used to refresh a token
# that already carries this client's refresh_token (e.g. one reused from
# ``yamusic_token``). A fresh token must be obtained via the developer.yandex.com
# page or pasted in; this client cannot start an interactive flow (see module
# docstring).
CLIENT_ID = "23cabbbdc6cd418abb4b39c32c41195d"
CLIENT_SECRET = "53bc75238f0c4d08a118e51fe9203300"  # noqa: S105

HTTP_TIMEOUT = 30
TOKEN_REFRESH_MARGIN = 60


class YandexDiskError(RuntimeError):
    """Raised for Yandex Disk API / OAuth failures."""


class TokenStore:
    """Yandex Disk OAuth credentials in the ``yandex_disk.auth`` config block.

    Only the fields the refresh flow needs are persisted, keeping
    ``config/config.yaml`` readable and free of token-response noise.
    """

    KEEP = (
        "access_token",
        "refresh_token",
        "expires_at",
        "scope",
    )

    def __init__(self, config_path: Path, section: str = "yandex_disk"):
        self.path = Path(config_path)
        self.section = section

    def _section(self) -> Dict[str, Any]:
        try:
            config = self._load_yaml()
        except FileNotFoundError:
            return {}
        section = config.get(self.section) or {}
        return dict(section) if isinstance(section, dict) else {}

    def _load_yaml(self) -> Dict[str, Any]:
        import yaml

        try:
            config = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise YandexDiskError(f"Corrupt config file {self.path}: {e}") from e
        return config if isinstance(config, dict) else {}

    def load(self) -> Dict[str, Any]:
        auth = self._section().get("auth")
        return dict(auth) if isinstance(auth, dict) else {}

    def _write(self, auth: Dict[str, Any]) -> None:
        section = self._section()
        if auth:
            section["auth"] = auth
        else:
            section.pop("auth", None)
        try:
            update_section(self.path, self.section, section)
        except ValueError as e:
            raise YandexDiskError(str(e)) from e

    def save(self, data: Dict[str, Any]) -> None:
        auth = {k: data[k] for k in self.KEEP if data.get(k) not in (None, "")}
        self._write(auth)

    def clear(self) -> None:
        self._write({})


def _flush() -> None:
    """Force stdout out so the prompt stays visible while waiting for input."""
    import sys

    sys.stdout.flush()


class _OAuthError(YandexDiskError):
    """Internal: an OAuth token request rejected with a known error code."""

    def __init__(self, code: str, description: str):
        self.code = code
        self.description = description
        super().__init__(f"{code}: {description}" if description else code)


def _token_response_error(resp: requests.Response) -> Optional[_OAuthError]:
    """Parse a non-2xx OAuth token response into a structured error, if any."""
    try:
        payload = resp.json()
    except ValueError:
        return None
    error = payload.get("error")
    if not error:
        return None
    return _OAuthError(str(error), str(payload.get("error_description") or ""))


class YandexDiskClient:
    """Minimal REST client for Yandex Disk (list, upload, download, delete)."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        api_base: str = API_BASE,
    ):
        self.api_base = api_base.rstrip("/")
        self.token_store = TokenStore(config_path or paths.DEFAULT_CONFIG_FILE)
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "MusicCLI/0.1 (Yandex Disk)"
        self.http.trust_env = False  # ignore system proxy; go direct

    # ===== Auth =====

    def is_authorized(self) -> bool:
        if os.environ.get("YANDEX_DISK_TOKEN"):
            return True
        return bool(self.token_store.load().get("access_token"))

    def status(self) -> Dict[str, Any]:
        data = self.token_store.load()
        return {
            "api_base": self.api_base,
            "authorized": self.is_authorized(),
            "expires_at": data.get("expires_at"),
            "scope": data.get("scope") or "(default)",
            "config_file": str(self.token_store.path),
            "env_override": bool(os.environ.get("YANDEX_DISK_TOKEN")),
        }

    def login(self) -> Dict[str, Any]:
        """Ask for a Yandex OAuth token (paste or reuse) and persist it.

        Two sources, both non-interactive to fetch here:

        - **developer.yandex.com** — the page for a Yandex app issues an
          ``Access token`` (and, if the app has refresh enabled, a
          ``Refresh token``). Paste both.
        - **Reuse your Music token** — the general-purpose Yandex token you
          already keep as ``yamusic_token`` works for the Disk API too.

        Returns the stored credential dict.
        """
        print(green("Yandex Disk needs a Yandex OAuth access token."))
        print(cyan("  How to get one:"))
        print("   a) Open a Yandex app at https://developer.yandex.com (OAuth + 'Cloud Disk'),")
        print("      and copy the \"Access token\" (and \"Refresh token\" if shown).")
        print("   b) Or reuse the general Yandex token you already use for Yandex Music")
        print("      (yamusic_token) — it is the same token family and works for the Disk API.")
        _flush()

        access = input("Yandex access token (or paste it): ").strip()
        if not access:
            raise YandexDiskError("No access token given — login cancelled.")
        refresh = input("Refresh token (paste if you have one, else press Enter): ").strip() or None

        data = self._store_token({
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 0,
            "scope": "disk",
            # A pasted token has no known expiry: mark it as far in the future so
            # _ensure_authorized uses it until the API says it is invalid (401 →
            # one refresh attempt, then a clear "re-login" error).
            "expires_at": time.time() + 10 * 365 * 86400,
        })
        logger.info("Yandex Disk token stored (refreshable=%s)", bool(refresh))
        return data

    def _token_request(self, grant_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Call the OAuth token endpoint (currently used for the refresh grant)."""
        payload = {
            "grant_type": grant_type,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            **data,
        }
        resp = self.http.post(TOKEN_ENDPOINT, data=payload, timeout=HTTP_TIMEOUT)
        self._raise_for_oauth(resp, f"the {grant_type} token request")
        token = resp.json()
        if not token.get("access_token"):
            raise YandexDiskError(f"Token response has no access_token: {token}")
        return token

    def logout(self) -> None:
        self.token_store.clear()

    def _store_token(self, token: Dict[str, Any]) -> Dict[str, Any]:
        data = {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            # Honor a caller-provided expiry; otherwise derive it from expires_in.
            "expires_at": token.get("expires_at") or time.time() + int(token.get("expires_in", 3600)),
            "scope": token.get("scope") or "default",
        }
        self.token_store.save(data)
        return data

    def _refresh_token(self) -> str:
        data = self.token_store.load()
        refresh = data.get("refresh_token")
        if not refresh:
            raise YandexDiskError(
                "Yandex Disk authorization expired and cannot be refreshed; run Log in again."
            )
        token = self._token_request("refresh_token", {"refresh_token": refresh})
        data.update(
            {
                "access_token": token.get("access_token"),
                "refresh_token": token.get("refresh_token") or refresh,
                "expires_at": time.time() + int(token.get("expires_in", 3600)),
                "scope": token.get("scope") or data.get("scope") or "default",
            }
        )
        self.token_store.save(data)
        return token["access_token"]

    def _raise_for_oauth(self, resp: requests.Response, action: str) -> None:
        if resp.ok:
            return
        oauth_error = _token_response_error(resp)
        if oauth_error is not None:
            raise oauth_error
        raise YandexDiskError(
            f"Yandex OAuth '{action}' failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )

    def _access_token(self) -> str:
        env_token = os.environ.get("YANDEX_DISK_TOKEN")
        if env_token:
            return env_token

        data = self.token_store.load()
        token = data.get("access_token")
        if not token:
            raise YandexDiskError("Not logged in to Yandex Disk. Use the 'log in' command first.")

        expires_at = data.get("expires_at")
        if expires_at and float(expires_at) - TOKEN_REFRESH_MARGIN < time.time():
            token = self._refresh_token()
        return token

    def _reauth_after_401(self) -> None:
        if os.environ.get("YANDEX_DISK_TOKEN"):
            raise YandexDiskError("YANDEX_DISK_TOKEN was rejected by the Yandex Disk API.")
        data = self.token_store.load()
        if not data.get("refresh_token"):
            raise YandexDiskError("Yandex Disk authorization expired; run Log in again.")
        self._refresh_token()

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token()}"}

    # ===== Core request =====

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        data: Any = None,
        files: Any = None,
        stream: bool = False,
    ) -> requests.Response:
        """Issue an authenticated API request, refreshing once on HTTP 401."""
        url = f"{self.api_base}{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        for attempt in range(2):
            resp = self.http.request(
                method,
                url,
                headers=self._headers(),
                params=None,
                data=data,
                files=files,
                stream=stream,
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 401 and attempt == 0:
                resp.close()
                self._reauth_after_401()
                continue
            return resp
        raise YandexDiskError("Yandex Disk request failed after re-authenticating.")

    def _check(self, resp: requests.Response) -> Any:
        if resp.ok:
            try:
                return resp.json()
            except ValueError:
                return resp.text
        detail = self._error_detail(resp)
        raise YandexDiskError(
            f"Yandex Disk request failed (HTTP {resp.status_code}): {detail}"
        )

    @staticmethod
    def _error_detail(resp: requests.Response) -> str:
        try:
            payload = resp.json()
        except ValueError:
            return (resp.text or "").strip()[:300]
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("description")
            if message:
                return str(message)[:300]
        return (resp.text or "")[:300]

    # ===== File operations =====

    def list_dir(self, path: str = "") -> List[Dict[str, Any]]:
        """List the contents of a directory. ``path`` is a Disk path (e.g. ``/music``)."""
        body = self._check(self._request("GET", "/api/files", params={"path": path or "/"}))
        return body.get("items", []) if isinstance(body, dict) else []

    def get_info(self, path: str) -> Dict[str, Any]:
        """Metadata for a single resource (file or directory)."""
        return self._check(self._request("GET", "/api/resources", params={"path": path}))

    def exists(self, path: str) -> bool:
        """True if the resource exists; False if the API reports it missing."""
        resp = self._request("HEAD", "/api/resources", params={"path": path})
        try:
            if resp.status_code == 204:
                return True
            if resp.status_code == 404:
                return False
            self._check(resp)
            return True
        finally:
            resp.close()

    def download(self, path: str, dest: Optional[Path] = None) -> Optional[Path]:
        """Download a Disk file to ``dest`` (a Path or a directory).

        If ``dest`` is a directory (or omitted), the file's base name is used.
        Returns the destination path, or None on failure (logged).
        """
        resp = self._request("GET", "/api/files", params={"path": path}, stream=True)
        try:
            if resp.status_code == 404:
                logger.warning("Yandex Disk download: %s not found", path)
                return None
            if not resp.ok:
                detail = self._error_detail(resp)
                logger.error("Yandex Disk download of %s failed (HTTP %s): %s", path, resp.status_code, detail)
                return None
            name = Path(path).name or "download"
            target = Path(dest) if dest else paths.DOWNLOAD_DIR / "yandex_disk" / name
            if target.is_dir():
                target = target / name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(target, "wb") as out:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if chunk:
                            out.write(chunk)
            except OSError as e:
                logger.error("Yandex Disk download of %s failed to write: %s", path, e)
                target.unlink(missing_ok=True)
                return None
        finally:
            resp.close()
        logger.info("Yandex Disk downloaded %s -> %s", path, target)
        return target

    def upload(
        self,
        local: Path,
        path: str,
        overwrite: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Upload a local file to Disk path ``path``.

        Uses the two-step reserve/commit protocol. On a conflict (409) the file
        is left untouched unless ``overwrite`` is set. Returns the committed
        resource dict, or None on failure (logged).
        """
        local = Path(local)
        if not local.is_file():
            raise YandexDiskError(f"Cannot upload: {local} is not a file")
        size = local.stat().st_size

        reserve = {
            "path": path,
            "size": size,
            "checksum": self._md5(local),
        }
        resp = self._request("POST", "/api/files/upload/reserve", data=reserve)
        if resp.status_code == 409 and not overwrite:
            detail = self._error_detail(resp)
            logger.warning("Yandex Disk upload: %s already exists (conflict): %s", path, detail)
            resp.close()
            return None
        body = self._check(resp)
        if not isinstance(body, dict):
            resp.close()
            return None
        upload_url = body.get("upload_url")
        if not upload_url:
            resp.close()
            return None

        with open(local, "rb") as f:
            put = self.http.put(upload_url, data=f, timeout=HTTP_TIMEOUT)
        if put.status_code not in (200, 201):
            logger.error(
                "Yandex Disk upload of %s failed during PUT (HTTP %s): %s",
                local, put.status_code, (put.text or "")[:200],
            )
            return None

        commit = {
            "path": path,
            "size": size,
            "upload_id": body.get("upload_id"),
        }
        commit_resp = self._request("POST", "/api/files/upload/commit", data=commit)
        committed = self._check(commit_resp)
        if not isinstance(committed, dict):
            return None
        logger.info("Yandex Disk uploaded %s -> %s", local, path)
        return committed

    def delete(self, path: str) -> bool:
        """Delete a file or directory. Returns True on success, raises otherwise."""
        resp = self._request("DELETE", "/api/files", params={"path": path})
        try:
            if resp.status_code in (200, 204):
                logger.info("Yandex Disk deleted %s", path)
                return True
            self._check(resp)
            return False
        finally:
            resp.close()

    # ===== Helpers =====

    @staticmethod
    def _md5(file_path: Path) -> str:
        import hashlib

        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
