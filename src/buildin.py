"""Buildin.ai MCP client.

This module is deliberately self-contained: it implements the MCP Streamable
HTTP transport and the OAuth 2.1 authorization-code flow (PKCE + dynamic
client registration) that the official Buildin MCP server advertises. It only
uses ``requests`` (already a project dependency), so no MCP SDK is required.

The client is generic: it can list and call any tool the Buildin MCP server
exposes. Music-specific workflows can be layered on top later.

Login flow (``BuildinClient.login``):

1. Discover the protected-resource and authorization-server metadata.
2. Register a public client dynamically for a temporary ``127.0.0.1`` callback.
3. Open the Buildin consent page in the browser; wait for the callback.
4. Exchange the authorization code (PKCE) and store the tokens in
   ``config/buildin_tokens.json`` (gitignored, mode 0600).

Set ``BUILDIN_ACCESS_TOKEN`` to bypass the stored token (useful for scripts and
tests); set ``buildin.mcp_url`` in ``config/config.yaml`` to point at another
MCP server implementing the same OAuth metadata.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from . import paths

DEFAULT_MCP_URL = "https://mcp.buildin.ai/message"
CALLBACK_PATH = "/callback"
AUTH_TIMEOUT = 300
HTTP_TIMEOUT = 120
TOKEN_REFRESH_MARGIN = 60
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "Music CLI"


class BuildinError(RuntimeError):
    """Raised for Buildin MCP/OAuth failures."""


class TokenStore:
    """JSON token file with owner-only permissions."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            raise BuildinError(f"Corrupt Buildin token file {self.path}: {e}") from e

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def _pkce_pair() -> Tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _append_query(url: str, params: Dict[str, str]) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    server: "_CallbackServer"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        self.server.result = {
            "code": params.get("code", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
            "error_description": params.get("error_description", [None])[0],
        }

        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>Buildin authorization</title>"
            "<p>Authorization received. You can close this tab and return to the terminal.</p>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


class _CallbackServer(HTTPServer):
    result: Optional[Dict[str, Any]] = None


class BuildinClient:
    """Minimal MCP Streamable HTTP client for Buildin.ai."""

    def __init__(
        self,
        mcp_url: str = DEFAULT_MCP_URL,
        token_file: Optional[Path] = None,
    ):
        self.mcp_url = mcp_url
        self.token_store = TokenStore(token_file or paths.BUILDIN_TOKENS_FILE)
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "MusicCLI/0.1 (Buildin MCP)"
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
        self._request_id = 0

    # ===== Public API =====

    def is_authorized(self) -> bool:
        if os.environ.get("BUILDIN_ACCESS_TOKEN"):
            return True
        return bool(self.token_store.load().get("access_token"))

    def status(self) -> Dict[str, Any]:
        data = self.token_store.load()
        expires_at = data.get("expires_at")
        return {
            "mcp_url": self.mcp_url,
            "authorized": self.is_authorized(),
            "expires_at": expires_at,
            "token_file": str(self.token_store.path),
            "resource": data.get("resource"),
        }

    def login(self) -> Dict[str, Any]:
        """Run the interactive OAuth flow and persist tokens."""
        metadata = self._discover_metadata()
        server, port = self._start_callback_server()
        redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"

        try:
            client = self._register_client(metadata, redirect_uri)
            verifier, challenge = _pkce_pair()
            state = secrets.token_urlsafe(24)

            params = {
                "response_type": "code",
                "client_id": client["client_id"],
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "resource": metadata["resource"],
            }
            scopes = metadata.get("scopes_supported") or []
            if scopes:
                params["scope"] = " ".join(scopes)

            authorize_url = _append_query(metadata["authorization_endpoint"], params)
            print("Opening the Buildin authorization page in your browser...")
            print(f"If it does not open, visit:\n{authorize_url}\n")
            webbrowser.open(authorize_url)

            code = self._wait_for_callback(server, state)
        finally:
            server.server_close()

        token = self._token_request(
            metadata["token_endpoint"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client["client_id"],
                "code_verifier": verifier,
                "resource": metadata["resource"],
            },
            client_secret=client.get("client_secret"),
        )

        data: Dict[str, Any] = {
            **token,
            "client_id": client["client_id"],
            "client_secret": client.get("client_secret"),
            "redirect_uri": redirect_uri,
            "resource": metadata["resource"],
            "token_endpoint": metadata["token_endpoint"],
            "expires_at": time.time() + int(token.get("expires_in", 3600)),
        }
        self.token_store.save(data)
        self._reset_session()
        return data

    def logout(self) -> None:
        self.token_store.clear()
        self._reset_session()

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._rpc("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    # ===== OAuth helpers =====

    def _discover_metadata(self) -> Dict[str, Any]:
        parsed = urlparse(self.mcp_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        resource_urls = (
            f"{origin}/.well-known/oauth-protected-resource{parsed.path}",
            f"{origin}/.well-known/oauth-protected-resource",
        )
        resource = self._get_json(resource_urls, "protected-resource metadata")

        auth_servers = resource.get("authorization_servers") or [origin]
        auth_server = str(auth_servers[0]).rstrip("/")
        auth_urls = (
            f"{auth_server}/.well-known/oauth-authorization-server",
            f"{auth_server}/.well-known/openid-configuration",
        )
        auth = self._get_json(auth_urls, "authorization-server metadata")

        return {
            **auth,
            "resource": resource.get("resource", self.mcp_url),
            "scopes_supported": resource.get("scopes_supported", []),
        }

    def _get_json(self, urls: Tuple[str, ...], label: str) -> Dict[str, Any]:
        errors = []
        for url in urls:
            try:
                resp = self.http.get(url, timeout=30)
            except requests.RequestException as e:
                errors.append(f"{url}: {e}")
                continue
            if resp.ok:
                try:
                    return resp.json()
                except ValueError:
                    errors.append(f"{url}: invalid JSON")
                    continue
            errors.append(f"{url}: HTTP {resp.status_code}")
        raise BuildinError("Could not load " + label + ":\n  " + "\n  ".join(errors))

    def _start_callback_server(self) -> Tuple[_CallbackServer, int]:
        server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
        port = server.server_address[1]
        return server, port

    def _register_client(self, metadata: Dict[str, Any], redirect_uri: str) -> Dict[str, Any]:
        endpoint = metadata.get("registration_endpoint")
        if not endpoint:
            raise BuildinError(
                "The authorization server does not support dynamic client registration; "
                "a pre-registered client is required."
            )

        payload: Dict[str, Any] = {
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        scopes = metadata.get("scopes_supported") or []
        if scopes:
            payload["scope"] = " ".join(scopes)

        try:
            resp = self.http.post(endpoint, json=payload, timeout=30)
        except requests.RequestException as e:
            raise BuildinError(f"Client registration failed: {e}") from e

        if not resp.ok:
            raise BuildinError(
                f"Client registration failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        try:
            client = resp.json()
        except ValueError as e:
            raise BuildinError("Client registration returned invalid JSON") from e
        if "client_id" not in client:
            raise BuildinError(f"Client registration response has no client_id: {client}")
        return client

    def _wait_for_callback(self, server: _CallbackServer, expected_state: str) -> str:
        deadline = time.time() + AUTH_TIMEOUT
        while time.time() < deadline:
            server.timeout = max(0.1, min(5.0, deadline - time.time()))
            server.handle_request()

            result = server.result
            if not result:
                continue
            if result.get("error"):
                detail = result.get("error_description") or ""
                raise BuildinError(f"Authorization failed: {result['error']} {detail}".strip())
            if not result.get("code"):
                raise BuildinError("Authorization callback did not include a code.")
            if result.get("state") != expected_state:
                raise BuildinError("OAuth state mismatch; aborting authorization.")
            return result["code"]

        raise BuildinError(
            f"Timed out after {AUTH_TIMEOUT}s waiting for the authorization callback."
        )

    def _token_request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        client_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = dict(data)
        if client_secret:
            payload.setdefault("client_secret", client_secret)

        # Buildin's documentation shows JSON bodies; fall back to the standard
        # form encoding if the server rejects the content type.
        try:
            resp = self.http.post(endpoint, json=payload, timeout=30)
        except requests.RequestException as e:
            raise BuildinError(f"Token request failed: {e}") from e

        if resp.status_code in (400, 415) and "content" in resp.text.lower():
            resp = self.http.post(endpoint, data=payload, timeout=30)

        if not resp.ok:
            raise BuildinError(f"Token request failed (HTTP {resp.status_code}): {resp.text[:300]}")
        try:
            token = resp.json()
        except ValueError as e:
            raise BuildinError("Token endpoint returned invalid JSON") from e
        if not token.get("access_token"):
            raise BuildinError(f"Token response has no access_token: {token}")
        return token

    def _refresh(self, data: Dict[str, Any]) -> Dict[str, Any]:
        refresh_token = data.get("refresh_token")
        client_id = data.get("client_id")
        if not refresh_token or not client_id:
            raise BuildinError("Buildin session expired and cannot be refreshed; log in again.")

        token = self._token_request(
            data.get("token_endpoint") or self._discover_metadata()["token_endpoint"],
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "resource": data.get("resource", self.mcp_url),
            },
            client_secret=data.get("client_secret"),
        )
        data.update(token)
        data["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        self.token_store.save(data)
        return data

    def _access_token(self) -> str:
        env_token = os.environ.get("BUILDIN_ACCESS_TOKEN")
        if env_token:
            return env_token

        data = self.token_store.load()
        token = data.get("access_token")
        if not token:
            raise BuildinError("Not logged in to Buildin. Use the 'login' command first.")

        expires_at = data.get("expires_at")
        if expires_at and float(expires_at) - TOKEN_REFRESH_MARGIN < time.time():
            token = self._refresh(data)["access_token"]
        return token

    def _refresh_after_401(self) -> None:
        if os.environ.get("BUILDIN_ACCESS_TOKEN"):
            raise BuildinError("BUILDIN_ACCESS_TOKEN was rejected by the MCP server.")
        data = self.token_store.load()
        if not data.get("refresh_token"):
            raise BuildinError("Buildin authorization expired; log in again.")
        self._refresh(data)

    # ===== MCP transport =====

    def _reset_session(self) -> None:
        self._session_id = None
        self._protocol_version = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _ensure_session(self) -> None:
        if self._session_id:
            return

        request_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "0.1.0"},
            },
        }

        for attempt in range(2):
            resp = self.http.post(
                self.mcp_url, json=payload, headers=self._headers(), stream=True, timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 401 and attempt == 0:
                resp.close()
                self._refresh_after_401()
                continue
            result = self._read_response(resp, request_id)
            self._session_id = resp.headers.get("Mcp-Session-Id")
            self._protocol_version = result.get("protocolVersion") or PROTOCOL_VERSION
            break
        else:
            raise BuildinError("Could not initialize the Buildin MCP session.")

        # Notify the server that initialization is complete.
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = self.http.post(
            self.mcp_url,
            json=notification,
            headers=self._headers(),
            stream=True,
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code >= 400:
            raise BuildinError(
                f"MCP initialization notification failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )

    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._ensure_session()

        request_id = self._next_id()
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params

        for attempt in range(2):
            resp = self.http.post(
                self.mcp_url, json=payload, headers=self._headers(), stream=True, timeout=HTTP_TIMEOUT
            )

            if resp.status_code == 401 and attempt == 0:
                resp.close()
                self._refresh_after_401()
                continue

            if resp.status_code == 404 and attempt == 0:
                resp.close()
                # Session expired: initialize again and retry.
                self._reset_session()
                self._ensure_session()
                continue

            return self._read_response(resp, request_id)

        raise BuildinError(f"MCP request '{method}' failed after re-authenticating.")

    def _read_response(self, resp: requests.Response, request_id: int) -> Dict[str, Any]:
        if resp.status_code >= 400:
            message = resp.text[:500] if resp.text else resp.reason
            raise BuildinError(f"MCP request failed (HTTP {resp.status_code}): {message}")

        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            message = self._read_sse(resp, request_id)
        else:
            try:
                message = resp.json()
            except ValueError as e:
                raise BuildinError(f"MCP server returned invalid JSON: {resp.text[:300]}") from e

        if "error" in message:
            error = message["error"]
            raise BuildinError(
                f"MCP error {error.get('code')}: {error.get('message')}"
            )
        if "result" not in message:
            raise BuildinError(f"Unexpected MCP response: {message}")
        return message["result"]

    def _read_sse(self, resp: requests.Response, request_id: int) -> Dict[str, Any]:
        data_lines: List[str] = []
        for raw_line in resp.iter_lines(decode_unicode=True):
            line = raw_line or ""
            if line.startswith(":"):
                continue
            if line == "":
                if data_lines:
                    message = self._parse_sse_event(data_lines)
                    data_lines.clear()
                    if message is not None and message.get("id") == request_id:
                        return message
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            message = self._parse_sse_event(data_lines)
            if message is not None and message.get("id") == request_id:
                return message
        raise BuildinError("MCP stream ended without a matching response.")

    @staticmethod
    def _parse_sse_event(data_lines: List[str]) -> Optional[Dict[str, Any]]:
        """Decode one SSE event; returns None for non-JSON events (e.g. pings)."""
        try:
            message = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return None
        if not isinstance(message, dict):
            return None
        # Server-initiated requests/notifications are not responses to us.
        if message.get("method"):
            return None
        return message
