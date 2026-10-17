# Architecture

Technical specification of the Music tool: modules, data flows, file schemas, known issues.

## Component overview

```
main.py
  │  parse_args()  ──►  setup_logging()  ──►  load_config("config/config.yaml")
  │
  ├── YaMusicHandle   (src/yamusic.py)  ──►  Yandex Music API  (yandex_music lib, direct)
  ├── YTMusicClient   (src/ytmusic.py)  ──►  YouTube Music API (ytmusicapi)
  │                                     ──►  YouTube downloads (yt-dlp, SOCKS5)
  ├── BuildinClient   (src/buildin.py)  ──►  Buildin MCP (OAuth 2.1 + Streamable HTTP)
  │
  └── CLI             (src/cli.py)      interactive loop, dispatches to both clients
```

Shared types: `Track` (src/track.py) — `NamedTuple(artist: str, name: str)`.

All runtime paths live in `src/paths.py` and are anchored to `PROJECT_ROOT` (the parent of `src/`), so relative paths never depend on the current working directory:

| Constant | Value |
|----------|-------|
| `CONFIG_DIR` | `<root>/config` |
| `DATA_DIR` | `<root>/data` |
| `DOWNLOAD_DIR` | `<root>/downloads` |
| `LOGS_DIR` | `<root>/logs` |
| `DEFAULT_CONFIG_FILE` | `config/config.yaml` |
| `BROWSER_AUTH_FILE` | `config/browser.json` |
| `PLAYLISTS_MAP_FILE` | `data/playlists_map.yaml` |
| `YAMUSIC_MAP_FILE` | `data/yamusic.yaml` |

`paths.resolve()` rebases user-supplied relative paths onto `PROJECT_ROOT`; `paths.resolve_config()` also accepts a bare `--config` file name and falls back to the old repo-root `config.yaml`. `resolve_config()` / `browser_auth_file()` warn when they use a legacy root-located file.

## Startup sequence

1. `main.py:22` calls `paths.ensure_directories()` → creates `config/`, `data/`, `downloads/`, `logs/` at the repo root.
2. `parse_args()` (src/args.py:4) — see flags in COMMANDS.md.
3. Relative `--output` is rebased into `logs/` (main.py:30-31).
4. `setup_logging()` (src/logger.py:9) — root logger → console (stdout) + `logs/music_api_<ts>.log`.
5. `load_config()` (src/config.py:11) resolves and reads the YAML file; `main.py:57` uses `config["token"]`.
6. `YaMusicHandle(token)` (src/yamusic.py:13) calls `Client(token).init()` → live API call at startup.
7. `YTMusicClient()` (src/ytmusic.py:72) builds a `requests.Session` with the SOCKS5 proxy and `YTMusic(auth=str(paths.browser_auth_file()))` (`config/browser.json`), then runs `_check_auth()` (src/ytmusic.py:91), which probes `get_account_info()` and warns — without aborting startup — if the auth is expired or unverifiable.
8. `BuildinClient` (src/buildin.py:130) is constructed from `buildin.mcp_url` but performs **no network access** until a Buildin command is used.
9. `CLI(yamusic, ytmusic, buildin, args).run()` (src/cli.py:320) — blocking interactive loop; `KeyboardInterrupt` exits cleanly.

Any exception in startup is caught in `main.py:83`, logged with traceback, exit code 1.

## Module reference

### src/yamusic.py — `YaMusicHandle`

Wraps a single `yandex_music.Client`. Methods:

| Method | Line | Purpose |
|--------|------|---------|
| `export_liked_tracks()` | 16 | Fetches all liked tracks, resolves each short track to a full `Track`; skips (and counts) broken ones with progress bars. |
| `get_playlists()` | 61 | `users_playlists_list()` with error swallowing. |
| `get_playlist_artists(playlist)` | 69 | Set of artist names in a playlist; bare `except` returns empty set. |
| `print_playlists()` | 80 | Debug print of title + kind. |
| `playlist_map(output_file)` | 85 | Writes `title → {kind, artists}` YAML to `data/temp_playlist_map.yaml` by default (used by Ya menu 4). |
| `create_playlist()` | 114 | Demo: creates a "Test" playlist. |
| `add_tracks_to_playlist(kind)` | 119 | Demo: inserts liked tracks `[15:25]` via `Difference`. |
| `delete_tracks_from_playlist(kind)` | 133 | Deletes all tracks via `Difference.add_delete`. |
| `delete_playlist(kind)` | 139 | Deletes a playlist. |
| `download_tracks(tracks, name)` | 143 | Downloads to `<root>/downloads/<name>/`; sanitizes `"/:*?¿`; picks max bitrate (≥192 kbps). |
| `download_playist(playlist)` | 172 | Resolves short tracks to full tracks, then `download_tracks` (note: method name has a typo upstream). |
| `download_playlists()` | 179 | Loop over all playlists. |
| `download_like_tracks()` | 184 | Liked tracks → `<root>/downloads/Like/`. |
| `sync_playlists_from_yaml(file)` | 191 | See flow 6 below; defaults to `data/yamusic.yaml`. |
| `check_tracks()` | 308 | See flow 7 below. |

### src/ytmusic.py — `YTMusicClient`

Wraps `ytmusicapi.YTMusic` plus yt-dlp. **Module import has side effects**: configures a module logger writing `logs/download_log_<ts>.log` (lines 14-37); `file_logger` writes file-only, console only ≥WARNING. `YtdlpLogger` (src/ytmusic.py:41) is a small yt-dlp logger adapter that routes yt-dlp errors/warnings into `file_logger` and collects error strings for the caller.

| Method | Line | Purpose |
|--------|------|---------|
| `__init__` | 72 | Session with hardcoded `socks5://127.0.0.1:1080`, `trust_env=False`; `YTMusic(auth=config/browser.json)`; calls `_check_auth()`. |
| `_check_auth()` | 91 | Startup probe of `get_account_info()`; warns (no abort) when auth is expired or unverifiable. |
| `import_liked_tracks(tracks)` | 120 | Search + `rate_song(..., "LIKE")` per track; returns `(not_found, errors)`. |
| `_get_best_result(results, track)` | 156 | Prefers "Top result", then exact title match, then first song. |
| `get_playlists(limit)` | 172 | `get_library_playlists`. |
| `print_playlists` / `create_playlist` / `get_playlist` / `get_playlist_artists` | 189-238 | Playlist CRUD helpers. |
| `add_playlist_items` / `delete_playlist` / `edit_playlist` / `get_playlist_tracks` | 240-283 | More CRUD; errors logged to `file_logger`. |
| `search_and_add_to_playlist` | 287 | Search + add, returns counts (not wired to the CLI). |
| `get_track_out_playlist()` | 334 | See flow 2 below. |
| `print_tracks(tracks)` | 374 | Writes `logs/tracks.txt` as `artist \t title \t videoId`. |
| `distribute_tracks()` | 391 | See flow 3 below. |
| `update_playlists_map(output_file)` | 407 | See flow 4 below; default output `data/playlists_map_updated.yaml`. |
| `load_playlist_tracks_map(yaml_file)` | 450 | Loads a track map (helper, not wired to CLI). |
| `download_track(video_id, ...)` | 470 | Single yt-dlp download. Embedded opts: format bestaudio→FFmpegExtractAudio, `concurrent_fragments: 6`, quiet + output suppression, `js_runtimes` (`node` ≥20 / `deno`) and `remote_components: ['ejs:github']` for YouTube's JS challenge, and a `YtdlpLogger` so failures are logged instead of silently swallowed. Returns the file path, or `None` when yt-dlp failed or the output file was not created (reason logged). |
| `download_all_playlists(...)` | 580 | See flow 5 below. |

### src/cli.py — `CLI`

Keeper of `self.mode` (`None` / `'ytmusic'` / `'yamusic'` / `'buildin'`), the three menus and dispatch. `move_tracks()` (line 95) implements the transfer flow and JSON report; everything else is thin glue. Buildin helpers live at src/cli.py:193-318. Contains hardcoded demo values — see Gotchas in AGENTS.md.

### src/buildin.py — `BuildinClient`

Self-contained Buildin.ai MCP client (no MCP SDK). It implements:

- **OAuth**: metadata discovery from `/.well-known/oauth-protected-resource` and `.well-known/oauth-authorization-server`, dynamic client registration (public client, `none` auth method), PKCE S256, a temporary `127.0.0.1` callback server (5-minute timeout), JSON token exchange with a form-encoded fallback, refresh-token grant, and a 0600 token file at `config/buildin_tokens.json`.
- **MCP Streamable HTTP**: `initialize` → `notifications/initialized`, `Mcp-Session-Id` / `MCP-Protocol-Version` headers, JSON *and* `text/event-stream` response parsing, one refresh on 401, one session re-init on 404.
- **Generic tools**: `list_tools()` → `tools/list`, `call_tool(name, arguments)` → `tools/call`.

| Method | Line | Purpose |
|--------|------|---------|
| `is_authorized()` / `status()` | 148 / 153 | Token presence + expiry info; no network |
| `login()` | 164 | Full OAuth flow; persists tokens |
| `logout()` | 223 | Deletes tokens, resets session |
| `list_tools()` | 227 | Returns the server's tool list |
| `call_tool(name, args)` | 231 | Invokes a tool; returns the MCP `result` dict |
| `_discover_metadata()` | 236 | OAuth resource + authorization-server discovery |
| `_register_client()` | 281 | RFC 7591 dynamic client registration |
| `_wait_for_callback()` | 317 | Waits for the local OAuth callback |
| `_token_request()` / `_refresh()` | 339 / 369 | Token exchange and refresh |
| `_ensure_session()` / `_rpc()` | 435 / 479 | MCP session lifecycle and JSON-RPC calls |
| `_read_response()` / `_read_sse()` | 506 / 529 | JSON and SSE response decoding |

`BUILDIN_ACCESS_TOKEN` bypasses the stored token, which makes headless
integration and tests possible. The transport is protocol-version agnostic in
practice: it sends `2025-06-18` and adopts whatever version the server returns.

### src/buildin_maps.py — playlist maps ⇄ Buildin database

Syncs `data/playlists_map.yaml` + `data/yamusic.yaml` with a dedicated Buildin
page/database.

| Function | Line | Purpose |
|----------|------|---------|
| `export_maps(client)` | 53 | Seed/update the database from the local YAML maps; matches records by `(Platform, Title)`; batches creates/updates (50) with an idempotency key; reports orphaned records |
| `import_maps(client)` | 114 | Query the whole database (paginated), validate records, return the two maps plus per-platform diffs; no local writes |
| `write_imported_maps(result)` | 138 | Atomically rewrite the YAML files with `.bak` backups; skip a platform with zero records |
| `ensure_resources(client)` | 157 | Find/create the `Music Library` page and `Playlists` database; cache IDs in `config/buildin_music.json` |
| `query_all(client, db)` | 175 | Cursor pagination over `buildin_query_database` |
| `_records_to_maps` / `_record_properties` | 231 / 223 | Buildin record ⇄ `{id|kind, artists}` conversion |
| `_find_page` / `_find_database` / `_create_*` | 409-485 | Discovery and creation of the page/database |
| `_call` | 568 | `tools/call` wrapper that parses the JSON text payload and raises `MapSyncError` on `isError` |

Database schema: `Title` (title), `Platform` (select: YouTube/Yandex),
`External ID` (rich_text), `Artists` (rich_text, newline-separated). Titles are
normalized with `:` → ` -` on import, matching the YAML key convention.
Buildin records cannot be deleted through MCP, so removed playlists must be
deleted in the UI.

### Support modules

- `src/paths.py` — project-wide path constants and helpers (`ensure_directories`, `resolve`, `resolve_config`, `browser_auth_file`). All paths anchor to the repo root; no module should use bare relative filenames.
- `src/config.py:11` — `load_config(path)` → dict; resolves `config.yaml` in `config/` (bare name) or the given path; raises on missing file / YAML error.
- `src/args.py:4` — argparse; `--no-proxy`, `--proxy-port`, `--log-file` are parsed but never wired.
- `src/logger.py:9` — `setup_logging(level, output_file)`; `get_logger(name)`. Logs go to `<root>/logs/`.

## Data flows

### 1. Transfer liked tracks (Ya → YT)
`CLI.transfer_tracks` (src/cli.py:119) → confirm → `move_tracks` (src/cli.py:76):
`export_liked_tracks()` → reverse order → `import_liked_tracks()` (search + LIKE each) → JSON `{liked_tracks, not_found, errors}` written to `args.output` (default `logs/tracks.json`).

### 2. Tracks out of playlist (YT)
`get_track_out_playlist` (src/ytmusic.py:327): fetch all library playlists; skip `SE`; the playlist with id `LM` is the liked-music source; every other playlist contributes its `videoId`s to a skip set. Result = liked tracks whose `videoId` is not in the skip set.

### 3. Distribute tracks (YT)
`distribute_tracks` (src/ytmusic.py:391): load `data/playlists_map.yaml`; take flow 2's track list; for each mapped playlist, add tracks whose first artist is in the map's `artists` list via `add_playlist_items`.

### 4. Update playlist map (YT)
`update_playlists_map` (src/ytmusic.py:407): list playlists, drop `LM`/`SE`, for each fetch full playlist + artist set → `title(':'→' -') → {id, artists}` YAML written to `data/playlists_map_updated.yaml` (review, then replace `data/playlists_map.yaml`).

### 5. Download all playlists (YT)
`download_all_playlists` (src/ytmusic.py:580): per playlist (excluding `LM`/`SE`) → folder `<ytmusic_download_dir>/<safe_title>/` → load `track_map_<safe_title>.yaml` if present → skip tracks whose `videoId` is in the map **and** whose file still exists on disk → download via `download_track` (yt-dlp) → update map (every 5 entries + at end) → aggregate stats printed and logged. A `None` return from `download_track` counts as a failure and the reason is in `logs/download_log_<ts>.log`.

### 6. Sync playlists from YAML (Ya, destructive)
`sync_playlists_from_yaml` (src/yamusic.py:191): read `data/yamusic.yaml` → index existing playlists by title → create missing ones (`users_playlists_create`) → **clear** each playlist (`delete_tracks_from_playlist`) → select liked tracks where `track artists ∩ playlist artists ≠ ∅` → insert in batches of 50 with the latest revision per batch (API limit workaround).

### 7. Check liked tracks (Ya, destructive)
`check_tracks` (src/yamusic.py:308): fetch each liked short track; if fetch raises, remove it from likes (`users_likes_tracks_remove`). Cleans up dead/region-blocked entries.

### 8. Buildin AI (MCP)
`CLI.buildin_login` (src/cli.py:200) → `BuildinClient.login` (src/buildin.py:164): discover OAuth metadata → dynamic client registration → browser consent (PKCE S256, `127.0.0.1` callback) → token exchange → `config/buildin_tokens.json`. `CLI.buildin_tools` / `buildin_call_tool` (src/cli.py:235,257) → `list_tools()` / `call_tool()` (src/buildin.py:227,231) → MCP `initialize`/`notifications/initialized` on first use → `tools/list` / `tools/call`. A 401 triggers one refresh-token exchange; a 404 triggers one session re-initialization.

### 9. Playlist maps ⇄ Buildin database
`export_maps` (src/buildin_maps.py:53): local YAML → desired records → ensure page/database → query existing records → create/update in batches of 50 via `buildin_mutate_database` (idempotency key per batch) → report unchanged/orphaned. `import_maps` (src/buildin_maps.py:114): `ensure_resources` → `buildin_query_database` paginated → validate platform/external id/kind → return maps + diffs → CLI confirmation → `write_imported_maps` writes both YAML files atomically with `.bak` backups (a platform with no Buildin records keeps its local file).

## File schemas

| File | Written by | Schema |
|------|-----------|--------|
| `config/config.yaml` | user | `token: <yandex OAuth>`, optional `ytmusic_download_dir: <path>` (YT output root, relative to repo root, default `downloads`) and optional `buildin.mcp_url`; flat; gitignored |
| `config/ex_config.yaml` | repo | template for the above |
| `config/browser.json` | `ytmusicapi browser --file config/browser.json` | ytmusicapi headers-auth file (live cookies; sensitive) |
| `config/buildin_tokens.json` | Buildin menu 1 | OAuth token set: `{access_token, refresh_token, token_type, scope, expires_in, expires_at, client_id, client_secret?, redirect_uri, resource, token_endpoint}`; mode 0600; gitignored |
| `config/buildin_music.json` | Buildin menu 6 | `{page_id, database_id}` cache for the `Music Library` page and `Playlists` database; gitignored |
| `data/playlists_map.yaml` | YT menu 5 / user | `Title: {id: PLxxxx, artists: [..]}` |
| `data/playlists_map_updated.yaml` | YT menu 5 | same schema; staging copy produced by the update command |
| `data/yamusic.yaml` | Ya menu 4 / user | `Title: {kind: 1084, artists: [..]}` |
| `data/temp_playlist_map.yaml` | Ya menu 4 | same schema as `data/yamusic.yaml` |
| `<ytmusic_download_dir>/<P>/track_map_<P>.yaml` | flow 5 | `<video_id>: {video_id, title, artist, file_path, filename, playlist, playlist_id, downloaded_at}` |
| `logs/tracks.txt` | YT menu 4 | TSV: `artist \t title \t videoId` |
| `logs/tracks.json` | flow 1 | `{liked_tracks: [{artist,name}], not_found: [...], errors: [...]}` |
| `logs/music_api_<ts>.log` | src/logger.py | timestamped app log |
| `logs/download_log_<ts>.log` | src/ytmusic.py | download-only log |

All YAML in the repo uses UTF-8 with `allow_unicode=True` (Cyrillic/Georgian titles).

## External dependencies & services

- **Yandex Music** (`yandex-music` 2.2.0): OAuth token; direct connection (no proxy); used for likes, playlists, downloads.
- **YouTube Music** (`ytmusicapi` 1.11.5): browser-cookie auth via `config/browser.json`; requests routed through SOCKS5 `127.0.0.1:1080`.
- **yt-dlp** (2026.08.19, keep it current) + **ffmpeg**: download & MP3 transcode; same SOCKS5 proxy. Options are passed in code — the Python API does **not** read `~/.config/yt-dlp/config`. YouTube extraction additionally requires a JS runtime (`node` ≥20 or `deno`; default is `deno` only, the code enables both) plus the EJS solver script (`remote_components: ['ejs:github']`, fetched from GitHub once and then cached).
- **Buildin.ai MCP** (`https://mcp.buildin.ai/message`): optional; direct HTTPS (no SOCKS5), OAuth 2.1 with dynamic client registration and PKCE, no API key. Only used when a Buildin command is invoked.

## Known issues / tech debt

1. Hardcoded demo values in `cli.py` (playlist index 1, video id `9zhK-QaEYZY`).
2. `--no-proxy`, `--proxy-port` (src/args.py:21,26) and `--log-file` (src/args.py:39) are parsed but unused; proxy is hardcoded in src/ytmusic.py (lines ~78 and ~509).
3. `YTMusicClient.__init__` performs no lazy init and `main.py` initializes both clients unconditionally — a proxy/network failure blocks startup even for Yandex-only work.
4. `config/config.yaml` holds a plaintext token; security depends entirely on `.gitignore`.
5. `config/browser.json` with live cookie hashes was committed to git; it is now gitignored and untracked — the exposed cookies should still be rotated (see AGENTS.md Security).
6. No tests, no CI, no non-interactive mode; verification is manual.
7. Broad `try/except` around library calls hides error details (worst: bare `except` in src/yamusic.py:76). yt-dlp failures are an exception now: `download_track` logs the real reason via `YtdlpLogger` (src/ytmusic.py:41) and returns `None`.
8. `get_playlist_artists` (YT) assumes `track["artists"]` is present for every track; malformed entries raise.
9. **yt-dlp must be kept current.** The old build (2026.3.17) failed every YouTube download with a 403 on the media request; updating yt-dlp (2026.08.19) fixed it. When downloads suddenly 403 again, update yt-dlp first. Note: the `download_track` opts (`js_runtimes`, `remote_components`) are required on modern yt-dlp for YouTube extraction.
10. `make clean` removes `__pycache__` only; `downloads/` cleanup is manual.
11. **Buildin map sync has no record deletion.** `BuildinClient` is generic, and `src/buildin_maps.py` adds the playlist-map workflow; the Buildin MCP API exposes no record-deletion tool, so removing a playlist locally leaves an orphan in Buildin (export reports it) that must be deleted in the UI. Importing keeps a platform's local YAML file when Buildin has no records for that platform, to avoid accidental wipes.
