# AGENTS.md

Entry point for AI agents and contributors working on this repository.

## What this is

A personal, interactive Python CLI that syncs a music library between **Yandex Music** and **YouTube Music** and downloads playlists/liked tracks to local MP3s. There is no web UI, no tests, no CI — it is run manually from a terminal.

## Quick start

```bash
cd ~/git/Music
uv sync                           # creates/updates .venv from uv.lock (Python 3.12)
uv run main.py                    # or: make run
```

Smoke check after any change: start the app, choose a mode, press `q` to quit. Anything beyond that touches live accounts (Yandex API + YouTube Music with real auth), so run real commands only with consent.

Requires: Python 3.12+ (PEP 701 f-strings), `ffmpeg`, node ≥20 (or deno; yt-dlp JS runtime), a local SOCKS5 proxy at `127.0.0.1:1080`, `uv` (dependency management), `config/config.yaml` (Yandex token, gitignored) and `config/browser.json` (YouTube auth, gitignored).

## Architecture map

| File | Role |
|------|------|
| `main.py` | Entry point: `parse_args` → `setup_logging` → loads `config/config.yaml` → `config["token"]` + `ytmusic_download_dir` (default `downloads`, relative paths anchored to the repo root) → `YaMusicHandle` + `YTMusicClient` → `CLI.run()`. Relative `--output` is redirected into `logs/` (main.py:30). Also calls `paths.ensure_directories()`. |
| `src/cli.py` | Interactive menu loop (`CLI`, src/cli.py:6). Mode select → YT or Ya menu → dispatch to clients. Contains hardcoded demo values (see Gotchas). |
| `src/paths.py` | Single source of truth for all filesystem paths (`PROJECT_ROOT`, `CONFIG_DIR`, `DATA_DIR`, `DOWNLOAD_DIR`, `LOGS_DIR`, config/auth/map files, `resolve*` helpers). Paths are anchored to the repo root, never to the CWD. |
| `src/yamusic.py` | `YaMusicHandle`: liked-track export, playlist map generation, Yandex playlist sync/CRUD, Yandex downloads (uses `yandex_music` built-in downloader). |
| `src/ytmusic.py` | `YTMusicClient`: `ytmusicapi` wrapper — search/like import, playlist CRUD, "tracks out of playlist" detection, yt-dlp MP3 downloads, per-playlist `track_map_*.yaml`. Also configures logging **at import time**. |
| `src/track.py` | `Track` NamedTuple `(artist, name)` — the transfer currency between both clients. |
| `src/args.py` / `src/config.py` / `src/logger.py` | argparse definitions, YAML config loader, console+file logging setup. |

Detailed module reference, data flows and file schemas: **docs/ARCHITECTURE.md**.
Full command reference with implementation mapping: **docs/COMMANDS.md**.

## Conventions

- Code, comments, docstrings and log messages are in English; user data (artist/title) is heavily Unicode (Cyrillic, Georgian) — always open YAML with `encoding='utf-8'` and dump with `allow_unicode=True` (existing pattern).
- Playlist map keys: `:` is replaced with ` -` to keep YAML keys safe.
- YAML schemas (do not change silently — the maps in `data/` are live data):
  - `data/playlists_map.yaml` (YouTube): `title → {id: <playlistId>, artists: [...]}`
  - `data/yamusic.yaml` (Yandex): `title → {kind: <numeric kind>, artists: [...]}`
- All runtime paths come from `src/paths.py`; do not add bare relative filenames like `open("x.yaml")` — that reintroduces CWD-dependent behavior.
- Special YouTube playlist IDs handled in code: `LM` = Liked Music, `SE` = excluded; both are skipped in distribution/download flows (src/ytmusic.py:347,351,425,612).
- File names for YT downloads come from the yt-dlp template `%(artist)s - %(title)s.%(ext)s`; Yandex downloads sanitize `/ " : ? * ¿` from names (src/yamusic.py:145).
- Type hints + short docstrings are used in `ytmusic.py`; `yamusic.py` is looser. Match the file you are editing; don't reformat unrelated code.

## Gotchas

- **Interactive only.** All flows require `input()`; there is no non-interactive mode. Do not launch the CLI expecting pipeable output.
- **Import-time side effects.** `import src.ytmusic` creates `logs/` (at the repo root) and a `logs/download_log_<ts>.log` file immediately (src/ytmusic.py:14-37).
- **Auth is checked at startup.** `YTMusicClient.__init__` runs `_check_auth()` (src/ytmusic.py:91) and warns — without aborting — when `config/browser.json` is expired (account endpoints then silently return logged-out/empty data) or cannot be verified (network/proxy down).
- **yt-dlp failures are logged, not silent.** `download_track` (src/ytmusic.py:470) passes a custom `YtdlpLogger` (src/ytmusic.py:41) so yt-dlp errors/warnings land in `logs/download_log_<ts>.log`, and returns `None` when yt-dlp fails or the output file was not created. Its opts also set `js_runtimes` (node ≥20 or deno) and `remote_components: ['ejs:github']` — YouTube requires a JS runtime plus the EJS solver script (fetched from GitHub once, then cached).
- **Hardcoded demo values in `cli.py`** — change these when touching those commands:
  - YT command 2 uses `playlists[1]` (src/cli.py:68)
  - YT command 8 downloads video `9zhK-QaEYZY` (src/cli.py:147)
- **Proxy is hardcoded** to `socks5://127.0.0.1:1080` in two places in `src/ytmusic.py` (API session ~line 78, yt-dlp opts ~line 509). `--no-proxy`/`--proxy-port` are parsed and logged but never wired; `--log-file` is parsed and unused.
- **Destructive commands exist.** Yandex menu 5 removes broken liked tracks; menu 6 clears each `data/yamusic.yaml` playlist before repopulating. Never trigger these in a test/demo without explicit user consent.
- **Transfer reverses order** before importing (src/cli.py:85) to mirror Yandex like chronology.
- **`config/config.yaml` schema is flat** (`token: ...`, optional `ytmusic_download_dir: <path>` for YouTube Music downloads, relative to the repo root). `config/ex_config.yaml` is the tracked template; `main.py` does `config["token"]` and will KeyError on other shapes.
- **`src/yamusic.py:76`** has a bare `except` that swallows all errors in `get_playlist_artists` — be aware when debugging missing artists.
- **Legacy fallback:** `config.yaml` / `browser.json` left in the repo root are still picked up (with a warning) by `paths.resolve_config()` / `paths.browser_auth_file()`. New code should use `config/` only.

## Security

- `config/config.yaml` holds a live Yandex token and is gitignored. Never print it or copy it into docs/logs.
- `config/browser.json` holds live YouTube auth cookies. It is now gitignored and untracked (previously committed — the cookies were exposed, rotate them). Do not paste its contents anywhere. Re-export procedure: README → *Re-exporting browser.json* — use DevTools **Copy as fetch (Node.js)**, not plain *Copy as fetch* (which drops the `Cookie` header).
- Do not add real tokens/cookies to `config/ex_config.yaml` or any tracked file.
- `downloads/`, `logs/`, `__pycache__/`, `.venv/`, `config/config.yaml` and `config/browser.json` are gitignored — don't force-add them.

## Where to change what

| Task | Touch |
|------|-------|
| New menu command | `src/cli.py` (menu printer + handler) + `src/yamusic.py` or `src/ytmusic.py` |
| New Yandex API action | `src/yamusic.py` |
| New YouTube API / download action | `src/ytmusic.py` |
| New CLI flag | `src/args.py`, then wire it in `main.py` (and actually pass it to clients — see proxy gotcha) |
| New file / output location | `src/paths.py`, then reference the constant (never a bare relative path) |
| Change playlist matching rules | `distribute_tracks` (src/ytmusic.py:391) for YT, `sync_playlists_from_yaml` (src/yamusic.py:191) for Ya |

## Docs

- [README.md](README.md) — user-facing overview and setup
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data flows, schemas, known issues
- [docs/COMMANDS.md](docs/COMMANDS.md) — command reference with `file:line` mapping
