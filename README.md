# Music

Personal CLI tool for managing a music library between **Yandex Music** and **YouTube Music**, plus bulk downloading of playlists and liked tracks to local MP3 files.

It can:

- Transfer liked tracks from Yandex Music to YouTube Music (search + like).
- Keep YouTube Music playlists organized by artist using a YAML map (`data/playlists_map.yaml`).
- Keep Yandex Music playlists organized by artist using a YAML map (`data/yamusic.yaml`).
- Download YouTube Music playlists as MP3 via [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- Download Yandex Music playlists / liked tracks as MP3 via the `yandex-music` API.
- Track already-downloaded tracks per playlist with `track_map_*.yaml` files (resumable downloads).
- Optional **Buildin.ai** integration over MCP (OAuth login, generic tool browser) as a foundation for music ↔ Buildin workflows.
- Optional **Telegram bot** (Bot API): push notifications after sync/downloads and run commands (`/transfer`, `/download`, …) from a chat.
- Optional **Yandex Disk** (REST): list, upload, download and delete files/folders (paste a Yandex OAuth token, auto-refreshing).

## Requirements

- Linux, Python **3.12+** (the code uses PEP 701 f-strings with nested quotes)
- `ffmpeg` (required by yt-dlp for MP3 conversion): `sudo apt install ffmpeg`
- [uv](https://docs.astral.sh/uv/) for dependency management (`uv sync`)
- Node.js **≥20** (or deno) — yt-dlp needs a JS runtime for YouTube extraction; the EJS solver script is fetched from GitHub on first use and then cached
- A local SOCKS5 proxy on `127.0.0.1:1080` (e.g. ciadpi; Tor would be `9150`). The YouTube Music API client and yt-dlp are hardcoded to use it — see the [known issues](docs/ARCHITECTURE.md).
- Accounts / credentials (stored in `config/config.yaml`, gitignored):
  - Yandex Music OAuth token (`yamusic_token`)
  - Telegram bot token / api_id / api_hash / MTProxy secret (optional)
  - YouTube Music browser auth (`ytmusic.auth` in `config/config.yaml`; legacy `config/browser.json` is still accepted)
  - Yandex Disk OAuth token — written by the app under `yandex_disk.auth` after a paste-token login (optional)

Dependencies are managed with [uv](https://docs.astral.sh/uv/) — declared in `pyproject.toml`, pinned in `uv.lock`:

```
yandex-music  ytmusicapi  tqdm  pyyaml  requests[socks]  yt-dlp  telethon  qrcode
```

## Setup

```bash
cd ~/git/Music

# 1. Dependencies (creates .venv and installs from uv.lock)
uv sync

# 2. Configuration
cp config/ex_config.yaml config/config.yaml   # config.yaml is gitignored
$EDITOR config/config.yaml                     # yamusic_token (+ optional settings)

# 3. YouTube Music auth: export the headers, then merge them into config.yaml
uv run ytmusicapi browser --file config/browser.json
uv run python -m src.config_tools inline-browser
```

`config/config.yaml` holds everything (API tokens, Telegram, YouTube auth,
Buildin credentials):

```yaml
yamusic_token: "your_yandex_token"
ytmusic_download_dir: downloads   # optional; where YouTube Music MP3s are saved
telegram:                         # optional
  token: "123456789:AAH..."
  api_id: 1234567
  api_hash: "..."
  mtproto: {host: 127.0.0.1, port: 1443, secret: "..."}
buildin:                          # optional; `auth` is written by the app
  mcp_url: https://mcp.buildin.ai/message
ytmusic:                          # managed block; written by src.config_tools
  auth: {cookie: "__Secure-3PAPISID=...", authorization: "SAPISIDHASH ..."}
```

### Buildin.ai (optional)

The Buildin integration is off until you use it — startup makes no Buildin
requests. Configure a different MCP endpoint only if needed:

```yaml
buildin:
  mcp_url: https://mcp.buildin.ai/message   # default
```

Then choose mode `3` in the CLI and run `1` (Log in). The app discovers the
OAuth metadata, registers a public client dynamically, opens the Buildin
consent page, and stores the credentials in `config/config.yaml` under
`buildin.auth` (only the fields the client needs: access/refresh token, expiry,
client id, resource, token endpoint). Tokens refresh automatically and are
written back in place; `5` (Log out) removes them.

For scripts/tests you can bypass the stored token with `BUILDIN_ACCESS_TOKEN`.
The client is generic: `3` lists the MCP tools exposed by Buildin and `4`
calls any of them with JSON arguments.

#### Playlist maps as the source of truth

`6` (Export) and `7` (Import) mirror the local playlist maps to/from a
dedicated Buildin page:

- **Music Library** (top-level page, created on first export)
- **Playlists** (database under it)

Each record is one playlist with `Title`, `Platform` (`YouTube`/`Yandex`),
`External ID` (YouTube playlist id or Yandex kind) and `Artists` (one artist
name per line).

First run `6` to seed the page/database from `data/playlists_map.yaml` and
`data/yamusic.yaml`. After editing records in Buildin, run `7` to regenerate
the YAML files — it shows a per-platform diff and asks for confirmation, and
keeps a `.bak` copy of each file it overwrites. The page/database IDs are
cached in `config/buildin_music.json` (gitignored).

Caveats: Buildin has no MCP record-deletion tool, so playlists deleted locally
remain in Buildin (reported as *orphaned* by export) and reappear on the next
import until you delete them in the Buildin UI. Do not rename the `Platform`,
`External ID` or `Artists` properties. Titles are stored with `:` replaced by
` -` to match the YAML key convention.

### Re-exporting YouTube auth

YouTube auth expires after a while (Google session cookies go stale). Symptoms: empty results from account methods, or the startup warning. To refresh `ytmusic.auth` in `config/config.yaml`:

1. Log in to https://music.youtube.com and open DevTools (`F12`) → **Network** tab.
2. Type `browse` in the filter box and reload the page.
3. Right-click a `browse?prettyPrint=false` **POST** request → **Copy** → **Copy as fetch (Node.js)**.
   - Use the **(Node.js)** variant — plain *Copy as fetch* omits the `Cookie` header, which is exactly what breaks the export.
4. Export the headers, then merge them into `config.yaml`:

   ```bash
   cd ~/git/Music && uv run ytmusicapi browser --file config/browser.json
   # paste the copied block, then press Ctrl+D
   uv run python -m src.config_tools inline-browser
   ```

   The merge writes the `ytmusic.auth` block in place (marker-delimited), keeps
   the rest of the file and is idempotent. `config/browser.json` is no longer
   used by the app — you can delete it after the merge.

5. Sanity check: the merged headers must include `cookie` with `__Secure-3PAPISID`. `ytmusicapi` silently drops pasted lines that don't contain `': '` — a missing cookie line is the most common export failure.

These are live session cookies; `config/config.yaml` is gitignored and mode `0600` — never commit or paste its contents.

### Telegram (optional)

A Telegram bot that both **reports results** (after transfers, downloads, map
syncs) and **runs commands** from a chat. It is off until configured — startup
makes no Telegram requests.

Two transports are supported; the same bot and commands work with either:

| Transport | When to use | Config |
|-----------|-------------|--------|
| **Bot API** (default) | the machine can reach `api.telegram.org` | `telegram.token` |
| **MTProto** (Telethon) | Telegram is blocked and the only egress is a local MTProto proxy (`tg-ws-proxy`, `mtg`, …) | `telegram.token` + `api_id`/`api_hash` + `mtproto:` |

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and copy
   the token. An MTProto proxy secret is **not** a bot token — you still need
   the BotFather token.
2. In `config/config.yaml` add:

   ```yaml
   telegram:
     token: "123456789:AAH...your_bot_token"
     # optional; omit to auto-capture your chat on first contact
     # chats: [123456789]
     # proxy: true        # default; set false to hit api.telegram.org directly
   ```

   If `api.telegram.org` is unreachable, use the MTProto transport instead. Get
   `api_id`/`api_hash` at [my.telegram.org](https://my.telegram.org) (any app
   works; the bot itself signs in with its BotFather token):

   ```yaml
   telegram:
     token: "123456789:AAH...your_bot_token"
     api_id: 1234567
     api_hash: "0123456789abcdef0123456789abcdef"
     mtproto:
       host: 127.0.0.1
       port: 1443
       secret: "0123456789abcdef0123456789abcdef"
   ```

   The Telethon session is created at `config/telegram_mtproto.session`
   (gitignored) on first connect.

3. In the CLI, choose mode **4 (Telegram)**:
   - **1 Status** — bot identity, transport, chats.
   - **2 Send test message** — verify delivery.
   - **3 Broadcast message** — send a manual message to all chats.
   - **4 Allow users** — set a whitelist of Telegram user ids (empty = open).
   - **5 Start command listener** — command loop that answers bot commands
     (Ctrl+C to stop).
   - **6 User: status** — state of the separate user-account session.
   - **7 User: log in** — two ways: **QR** (default — scan with Telegram →
     Settings → Devices → Link Desktop Device; no code delivery) or a **login
     code** sent by Telegram to the app/SMS. The two-step password is asked if
     you set one.
   - **8 User: Saved Messages** — print the newest notes from your Saved
     Messages (asks how many, default 20).
   - **9 User: log out** — revokes that session and deletes its file.

A **bot account cannot see Saved Messages or your chats** — Telegram does not
allow it. Items 6–9 use a second, *user-account* session (`TelegramUserClient`,
`src/telegram_user.py`): same `api_id`/`api_hash` and MTProto proxy, its own
interactive login, and its authorization in `config/telegram_user.session`
(gitignored). Set `telegram.phone` in the config to skip the phone prompt.
Programmatic use: `TelegramUserClient(cfg).get_saved_messages(limit=50)` returns
`{id, date, text, media, out}` rows, newest first; page back with
`offset_id=<last id>`.

From Telegram, send `/help` to the bot for the command list: `/status`,
`/playlists`, `/ya`, `/transfer`, `/download`, `/yadownload`, `/liked`, `/maps`,
`/notify <text>`. Commands run on the listener thread and block until they
finish — long downloads take a while.

Notes:

- Without `telegram.mtproto` the bot talks to `api.telegram.org` **directly**.
  A local `tg-ws-proxy` on `1443` speaks MTProto, not HTTPS, so it cannot be
  used as an HTTP proxy. If you have a proxy that tunnels `api.telegram.org`,
  set `telegram.proxy: true` and `telegram.proxy_url: http://127.0.0.1:PORT`
  (or `socks5://...`) — this uses the Bot API, not MTProto.
- If no chat is configured, the listener auto-captures the first chat that
  messages the bot and stores it in `config/telegram.json` (gitignored).
- CLI operations (transfer, downloads, map export) automatically send a
  notification when Telegram is configured.
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` override the
  stored values for scripts/tests.

`config/telegram.json` holds the chat allow-list — no secret, but gitignored.

### Yandex Disk (optional)

File operations on your Yandex Disk: list, upload, download and delete. It is
off until configured — startup makes no Yandex requests.

1. In the CLI choose mode **5 (Yandex Disk)** → **1 Log in**. The login asks you
   to paste a **Yandex OAuth access token** (and, optionally, a refresh token).
   You can get one either from a Yandex app at https://developer.yandex.com
   (create the app with the "Cloud Disk" product), or — simplest — by reusing
   the general-purpose Yandex token you already use for Yandex Music
   (`yamusic_token`), which the Disk API also accepts. The token is stored under
   `yandex_disk.auth` (gitignored, mode `0600`) and, if it carries a refresh
   token, auto-refreshed. `7` (Log out) removes it.
   (The browser/device OAuth flows do not work with Yandex's public Music client,
   which is why login is paste-based.)
2. The menu:
   - **2 Status** — API base, scope, token state/expiry.
   - **3 List directory** — prompt for a Disk path (default `/`) and print its items.
   - **4 Download file** — prompt for a Disk file path and a local destination
     (default `downloads/yandex_disk/<name>`).
   - **5 Upload file** — prompt for a local file and a Disk target path (two-step
     reserve/commit; asks to confirm overwriting an existing file).
   - **6 Delete file/folder** — prompt for a Disk path, asks for confirmation,
     then deletes it (**destructive**).
   - **7 Log out** — remove the stored Yandex Disk token.

Commands 3, 4, 5 and 6 start the login flow automatically when not authorized.
For scripts/tests you can bypass the stored token with `YANDEX_DISK_TOKEN`.
The Disk client uses its own `requests` session that ignores the system proxy
(`trust_env=False`), since Yandex is reachable directly.

## Usage

```bash
uv run main.py             # or: make run
```

The tool is an interactive menu. Pick an API mode (YouTube Music, Yandex Music, Buildin AI, Telegram or Yandex Disk), then issue commands.

### YouTube Music mode

| # | Command | What it does |
|---|---------|--------------|
| 1 | List playlists | Prints your library playlists with their IDs |
| 2 | Get playlist artists | Prints artists of one playlist (currently hardcoded to `playlists[1]`) |
| 3 | Get tracks from liked playlist | Liked tracks that are not present in any other playlist |
| 4 | Print tracks to file | Writes `logs/tracks.txt` (`artist<TAB>title<TAB>videoId`) |
| 5 | Update playlist map | Writes `data/playlists_map_updated.yaml` (review it, then replace `data/playlists_map.yaml`) |
| 6 | Distribute tracks by playlists | Adds "out-of-playlist" tracks to playlists using `data/playlists_map.yaml` artist matching |
| 7 | Download all user playlists | Downloads every playlist as MP3 into `<ytmusic_download_dir>/<Playlist>/` via yt-dlp |
| 8 | Download track | Downloads a single hardcoded demo video ID |

### Yandex Music mode

| # | Command | What it does |
|---|---------|--------------|
| 1 | Transfer tracks to YouTube Music | Likes each Yandex liked track in YouTube Music (search + LIKE), writes result JSON |
| 2 | Download playlists | Downloads all Yandex playlists into `downloads/<Playlist>/` |
| 3 | Download liked tracks as playlist | Downloads liked tracks into `downloads/Like/` |
| 4 | Get playlist map | Writes `data/temp_playlist_map.yaml` (playlist title → kind + artists) |
| 5 | Playlist changes | Removes liked tracks that fail to fetch (broken/region-blocked) from likes |
| 6 | Sync playlists from yaml | **Destructive**: clears each playlist listed in `data/yamusic.yaml` and repopulates it from liked tracks by artist matching |

### Buildin AI mode

| # | Command | What it does |
|---|---------|--------------|
| 1 | Log in | Browser OAuth against `https://mcp.buildin.ai`; credentials saved to `config.yaml` (`buildin.auth`) |
| 2 | Show status | Prints the MCP endpoint, token file, auth state and token expiry |
| 3 | List MCP tools | Calls `tools/list` and prints tool names + descriptions |
| 4 | Call MCP tool | Prompts for a tool name and JSON arguments, calls `tools/call`, prints the result |
| 5 | Log out | Deletes the stored tokens and resets the MCP session |
| 6 | Export playlist maps to Buildin | Creates/updates the *Music Library* page and its *Playlists* database from the local YAML maps |
| 7 | Import playlist maps from Buildin | Reads the database, shows a diff, and (after confirmation) rewrites `data/playlists_map.yaml` / `data/yamusic.yaml` with `.bak` backups |

Commands 3, 4, 6 and 7 start the login flow automatically when not authorized.
The client speaks MCP Streamable HTTP, handles SSE and JSON responses, refreshes
expired tokens, and re-initializes the session if the server drops it.

### Telegram mode

Requires the `telegram:` section in `config/config.yaml` (see [Telegram (optional)](#telegram-optional)).

| # | Command | What it does |
|---|---------|--------------|
| 1 | Status | Prints the bot identity, known chats, proxy and allow-list |
| 2 | Send test message | Sends a test message to all known chats |
| 3 | Broadcast message | Prompts for a message and sends it to all known chats |
| 4 | Allow users | Sets the whitelist of Telegram user ids (empty = open) |
| 5 | Start command listener | Command loop answering bot commands (`/help` lists them); Ctrl+C stops |
| 6 | User: status | Prints the user-account session: phone, session path, logged-in account |
| 7 | User: log in | QR code scan (default, no code needed) or phone → code → two-step password |
| 8 | User: Saved Messages | Prints the newest Saved Messages (asks count, default 20) |
| 9 | User: log out | Revokes the user session on Telegram's side and deletes its file |

Items 1–5 use the **bot** account (notifications + commands). Items 6–9 use the
separate **user-account** session, which is the only way to touch Saved Messages
or personal dialogs (`TelegramUserClient.get_saved_messages()`); the bot cannot
see them.

CLI operations (transfer, downloads, map export) also push a notification to
Telegram automatically when it is configured.

### Yandex Disk mode

| # | Command | What it does |
|---|---------|--------------|
| 1 | Log in | Prompts for a Yandex OAuth access token (and optional refresh token) to paste — from developer.yandex.com or reused from `yamusic_token`; stores it in `config.yaml` (`yandex_disk.auth`) |
| 2 | Show status | Prints the API base, scope, config file and token state/expiry |
| 3 | List directory | Prompts for a Disk path and prints its items (name, type, size) |
| 4 | Download file | Prompts for a Disk file path and a local destination, then downloads it |
| 5 | Upload file | Prompts for a local file and a Disk target path; reserve/commit, with overwrite confirmation |
| 6 | Delete file/folder | Prompts for a Disk path and a confirmation, then deletes it (**destructive**) |
| 7 | Log out | Removes the stored Yandex Disk token |

Commands 3, 4, 5 and 6 start the login flow automatically when not authorized.
The client talks to `https://api.yandex.net/disk/` with a `requests` session that
bypasses the system proxy, refreshes the token when it nears expiry, and retries
once on an HTTP 401. `YANDEX_DISK_TOKEN` overrides the stored token.

### CLI flags

```
--config PATH      Config file (default: config/config.yaml)
--output NAME      Output JSON for transfer results (default: tracks.json, relative paths go to logs/)
--no-proxy         Disable proxy (parsed and logged, but not wired into the clients yet)
--proxy-port N     Proxy port, 1080 ciadpi / 9150 Tor (parsed and logged, but not wired yet)
--log-level LEVEL  DEBUG|INFO|WARNING|ERROR|CRITICAL (default: INFO)
--log-file NAME    Parsed but currently unused
```

## Repository layout

```
main.py                 Entry point: parse args, logging, init clients, start CLI
src/cli.py              Interactive menu loop and command dispatch
src/yamusic.py          Yandex Music client (transfer, downloads, playlist sync)
src/ytmusic.py          YouTube Music client (ytmusicapi + yt-dlp downloads)
src/color.py            ANSI color helpers (auto-disabled by NO_COLOR=1)
src/track.py            Track named tuple (artist, name)
src/buildin.py          Buildin.ai MCP client (OAuth login, tool calls)
src/buildin_maps.py     Playlist-map sync with a Buildin database
src/yandex_disk.py      Yandex Disk REST client (paste-token login, list/upload/download/delete)
src/paths.py            Project-wide path constants (anchored to the repo root)
src/config.py           YAML config loader
src/args.py             argparse definitions
src/logger.py           File-only logging setup
config/config.yaml      Yandex token + Telegram/Buildin credentials (gitignored)
config/ex_config.yaml   Example config template
config/browser.json     Legacy YouTube auth (optional, gitignored)
config/buildin_music.json   Cached Buildin page/database IDs (gitignored)
data/playlists_map.yaml YouTube playlist map: title -> {id, artists}
data/yamusic.yaml       Yandex playlist map: title -> {kind, artists}
pyproject.toml          Project metadata and dependencies (uv)
uv.lock                 Locked dependency versions
downloads/              Downloaded MP3s (Yandex Music; YouTube Music can be redirected via ytmusic_download_dir)
logs/                   Run logs, transfer result JSON and tracks.txt
```

## Data files

- `data/playlists_map.yaml` — YouTube Music side. Each key is a playlist title (colons replaced by ` -`), value: `{id: <playlistId>, artists: [...]}`. Used by *Distribute tracks* to decide which playlist a track belongs to.
- `data/yamusic.yaml` — Yandex Music side. Each key is a playlist title, value: `{kind: <playlist kind>, artists: [...]}`. Used by *Sync playlists from yaml*; playlists missing `kind` are created automatically.
- `<ytmusic_download_dir>/<Playlist>/track_map_<Playlist>.yaml` — per-playlist download bookkeeping: `video_id -> {title, artist, file_path, downloaded_at}`. Used to skip already-downloaded tracks; delete an entry to force re-download.
- Buildin *Music Library → Playlists* database — same data as the two YAML maps, one record per playlist (`Title`, `Platform`, `External ID`, `Artists`). Importing writes the YAML files and keeps `<file>.bak` copies.
- `config/buildin_music.json` — ID cache for the Buildin page/database. Delete it to make the next command rediscover/recreate them.

## Logging & outputs

- `logs/music_api_<timestamp>.log` — main run log (created by `src/logger.py`).
- `logs/download_log_<timestamp>.log` — download log (created by `src/ytmusic.py`).
- `logs/tracks.json` — transfer results (liked / not found / errors), when using the default `--output`.
- `logs/tracks.txt` — TSV dump written by YT menu 4.

All paths are anchored to the repository root, so the CLI can be launched from any directory (e.g. `uv run --project ~/git/Music ~/git/Music/main.py`).

## Troubleshooting

- **"missing 1 required positional argument: 'id'"** — a Yandex liked track with a broken artist reference; the exporter skips such tracks by design.
- **YouTube Music returns empty results (no error)** — the YouTube auth has expired: account endpoints silently return the logged-out view. The app warns about this at startup. Re-export it (see [Re-exporting YouTube auth](#re-exporting-youtube-auth)).
- **`Your cookie is missing the required value __Secure-3PAPISID`** — the exported headers didn't include the `cookie` header. Re-copy using **Copy as fetch (Node.js)** or *Copy request headers* — plain *Copy as fetch* strips cookies — and make sure the paste contains a line starting with `cookie:` (details in [Re-exporting YouTube auth](#re-exporting-youtube-auth)).
- **All YouTube requests fail / time out** — the tool expects a SOCKS5 proxy on `127.0.0.1:1080`. Start ciadpi (or edit the proxy in `src/ytmusic.py`).
- **Downloads fail with HTTP 403 errors** — usually an outdated yt-dlp (the 2026.3.17 build failed every download; 2026.08.19 works). Update it: `uv lock --upgrade-package yt-dlp && uv sync`. Recent yt-dlp versions need node ≥20 (or deno) and fetch the EJS solver from GitHub on first run. The exact yt-dlp error is logged to `logs/download_log_<timestamp>.log` (see *Known issues* in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **`config/config.yaml` not found** — you must create it from `config/ex_config.yaml`; it is intentionally gitignored.
- **Buildin login does not complete** — the flow needs a browser and a temporary `127.0.0.1` callback port, and must finish within 5 minutes. If the browser opened on another machine, copy the printed authorization URL to a local browser. Re-run `1` (Log in) to register a fresh callback.
- **`Buildin session expired and cannot be refreshed`** — run `5` (Log out) then `1` (Log in).
- **`The Buildin database 'Playlists' is empty`** — run `6` (Export) once to seed it from the local YAML maps.
- **`Buildin database is missing the 'External ID' property`** — a property was renamed in Buildin. Rename it back (the importer matches by the exact names `Platform`, `External ID`, `Artists`).
- **Import keeps a YAML file** — when Buildin has zero records for a platform, the corresponding local file is left untouched instead of being wiped.
- **MP3 conversion fails** — install `ffmpeg`.

## Security notes

- `config/config.yaml` holds the live Yandex token, Telegram credentials and Buildin OAuth tokens; it is gitignored and written with mode `0600` — never commit or paste it.
- YouTube auth cookies now live in `config/config.yaml` (`ytmusic.auth`), which is gitignored and mode `0600`. The legacy `config/browser.json` (if present) is still honoured as a fallback and stays gitignored. Do not paste their contents anywhere. Re-export procedure: README → *Re-exporting YouTube auth* — use DevTools **Copy as fetch (Node.js)**, not plain *Copy as fetch* (which drops the `Cookie` header).
- `config/buildin_music.json` only contains Buildin page/database IDs (no secrets) but is gitignored because it is local state.
- The Yandex Disk token lives in `config/config.yaml` (`yandex_disk.auth`) — gitignored and mode `0600`. It is written only by the app after a paste-token login and removed by `Yandex Disk → Log out`. Never paste its contents. `YANDEX_DISK_TOKEN` overrides it for scripts.
- `downloads/`, `logs/` and `__pycache__/` are generated and gitignored.

## More documentation

- [AGENTS.md](AGENTS.md) — entry point for AI agents / contributors (quick start, conventions, gotchas)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data flows, file schemas
- [docs/COMMANDS.md](docs/COMMANDS.md) — full CLI command reference with implementation mapping

## License

See [LICENSE](LICENSE).
