# Architecture

Technical specification of the Music tool: modules, data flows, file schemas, known issues.

## Component overview

```
main.py
  │  parse_args()  ──►  setup_logging()  ──►  load_config("config.yaml")
  │
  ├── YaMusicHandle   (src/yamusic.py)  ──►  Yandex Music API  (yandex_music lib, direct)
  ├── YTMusicClient   (src/ytmusic.py)  ──►  YouTube Music API (ytmusicapi)
  │                                     ──►  YouTube downloads (yt-dlp, SOCKS5)
  │
  └── CLI             (src/cli.py)      interactive loop, dispatches to both clients
```

Shared types: `Track` (src/track.py) — `NamedTuple(artist: str, name: str)`.

## Startup sequence

1. `main.py:21` creates `logs/` if missing.
2. `parse_args()` (src/args.py:4) — see flags in COMMANDS.md.
3. Relative `--output` is rebased into `logs/` (main.py:29-31).
4. `setup_logging()` (src/logger.py:8) — root logger → console (stdout) + `logs/music_api_<ts>.log`.
5. `load_config()` (src/config.py:8) reads the YAML file and `main.py:49` uses `config["token"]`.
6. `YaMusicHandle(token)` (src/yamusic.py:13) calls `Client(token).init()` → live API call at startup.
7. `YTMusicClient()` (src/ytmusic.py:69) builds a `requests.Session` with the SOCKS5 proxy and `YTMusic(auth="browser.json")`, then runs `_check_auth()` (src/ytmusic.py:86), which probes `get_account_info()` and warns — without aborting startup — if the auth is expired or unverifiable.
8. `CLI(yamusic, ytmusic, args).run()` (src/cli.py:174) — blocking interactive loop; `KeyboardInterrupt` exits cleanly.

Any exception in startup is caught in `main.py:65`, logged with traceback, exit code 1.

## Module reference

### src/yamusic.py — `YaMusicHandle`

Wraps a single `yandex_music.Client`. Methods:

| Method | Line | Purpose |
|--------|------|---------|
| `export_liked_tracks()` | 15 | Fetches all liked tracks, resolves each short track to a full `Track`; skips (and counts) broken ones with progress bars. |
| `get_playlists()` | 60 | `users_playlists_list()` with error swallowing. |
| `get_playlist_artists(playlist)` | 68 | Set of artist names in a playlist; bare `except` returns empty set. |
| `print_playlists()` | 79 | Debug print of title + kind. |
| `playlist_map(output_file)` | 84 | Writes `title → {kind, artists}` YAML (used by Ya menu 4). |
| `create_playlist()` | 112 | Demo: creates a "Test" playlist. |
| `add_tracks_to_playlist(kind)` | 117 | Demo: inserts liked tracks `[15:25]` via `Difference`. |
| `delete_tracks_from_playlist(kind)` | 131 | Deletes all tracks via `Difference.add_delete`. |
| `delete_playlist(kind)` | 137 | Deletes a playlist. |
| `download_tracks(tracks, name)` | 141 | Downloads to `downloads/<name>/`; sanitizes `"/:*?¿`; picks max bitrate (≥192 kbps). |
| `download_playist(playlist)` | 170 | Resolves short tracks to full tracks, then `download_tracks` (note: method name has a typo upstream). |
| `download_playlists()` | 177 | Loop over all playlists. |
| `download_like_tracks()` | 182 | Liked tracks → `downloads/Like/`. |
| `sync_playlists_from_yaml(file)` | 189 | See flow 6 below. |
| `check_tracks()` | 306 | See flow 7 below. |

### src/ytmusic.py — `YTMusicClient`

Wraps `ytmusicapi.YTMusic` plus yt-dlp. **Module import has side effects**: configures a module logger writing `logs/download_log_<ts>.log` (lines 12-35); `file_logger` writes file-only, console only ≥WARNING. `YtdlpLogger` (src/ytmusic.py:38) is a small yt-dlp logger adapter that routes yt-dlp errors/warnings into `file_logger` and collects error strings for the caller.

| Method | Line | Purpose |
|--------|------|---------|
| `__init__` | 70 | Session with hardcoded `socks5://127.0.0.1:1080`, `trust_env=False`; `YTMusic(auth="browser.json")`; calls `_check_auth()`. |
| `_check_auth()` | 86 | Startup probe of `get_account_info()`; warns (no abort) when auth is expired or unverifiable. |
| `import_liked_tracks(tracks)` | 113 | Search + `rate_song(..., "LIKE")` per track; returns `(not_found, errors)`. |
| `_get_best_result(results, track)` | 149 | Prefers "Top result", then exact title match, then first song. |
| `get_playlists(limit)` | 165 | `get_library_playlists`. |
| `print_playlists` / `create_playlist` / `get_playlist` / `get_playlist_artists` | 182-233 | Playlist CRUD helpers. |
| `add_playlist_items` / `delete_playlist` / `edit_playlist` / `get_playlist_tracks` | 235-278 | More CRUD; errors logged to `file_logger`. |
| `search_and_add_to_playlist` | 280 | Search + add, returns counts (not wired to the CLI). |
| `get_track_out_playlist()` | 327 | See flow 2 below. |
| `print_tracks(tracks)` | 367 | Writes `tracks.txt` as `artist \t title \t videoId`. |
| `distribute_tracks()` | 383 | See flow 3 below. |
| `update_playlists_map(output_file)` | 399 | See flow 4 below. |
| `load_playlist_tracks_map(yaml_file)` | 440 | Loads a track map (helper, not wired to CLI). |
| `download_track(video_id, ...)` | 460 | Single yt-dlp download. Embedded opts: format bestaudio→FFmpegExtractAudio, `concurrent_fragments: 6`, quiet + output suppression, `js_runtimes` (`node` ≥20 / `deno`) and `remote_components: ['ejs:github']` for YouTube's JS challenge, and a `YtdlpLogger` so failures are logged instead of silently swallowed. Returns the file path, or `None` when yt-dlp failed or the output file was not created (reason logged). |
| `download_all_playlists(...)` | 569 | See flow 5 below. |

### src/cli.py — `CLI`

Keeper of `self.mode` (`None` / `'ytmusic'` / `'yamusic'`), the two menus and dispatch. `move_tracks()` (line 76) implements the transfer flow and JSON report; everything else is thin glue. Contains hardcoded demo values — see Gotchas in AGENTS.md.

### Support modules

- `src/config.py:8` — `load_config(path)` → dict; raises on missing file / YAML error.
- `src/args.py:4` — argparse; `--no-proxy`, `--proxy-port`, `--log-file` are parsed but never wired.
- `src/logger.py:8` — `setup_logging(level, output_file)`; `get_logger(name)`.

## Data flows

### 1. Transfer liked tracks (Ya → YT)
`CLI.transfer_tracks` (src/cli.py:119) → confirm → `move_tracks` (src/cli.py:76):
`export_liked_tracks()` → reverse order → `import_liked_tracks()` (search + LIKE each) → JSON `{liked_tracks, not_found, errors}` written to `args.output` (default `logs/tracks.json`).

### 2. Tracks out of playlist (YT)
`get_track_out_playlist` (src/ytmusic.py:327): fetch all library playlists; skip `SE`; the playlist with id `LM` is the liked-music source; every other playlist contributes its `videoId`s to a skip set. Result = liked tracks whose `videoId` is not in the skip set.

### 3. Distribute tracks (YT)
`distribute_tracks` (src/ytmusic.py:383): load `playlists_map.yaml`; take flow 2's track list; for each mapped playlist, add tracks whose first artist is in the map's `artists` list via `add_playlist_items`.

### 4. Update playlist map (YT)
`update_playlists_map` (src/ytmusic.py:399): list playlists, drop `LM`/`SE`, for each fetch full playlist + artist set → `title(':'→' -') → {id, artists}` YAML.

### 5. Download all playlists (YT)
`download_all_playlists` (src/ytmusic.py:569): per playlist (excluding `LM`/`SE`) → folder `<ytmusic_download_dir>/<safe_title>/` → load `track_map_<safe_title>.yaml` if present → skip tracks whose `videoId` is in the map **and** whose file still exists on disk → download via `download_track` (yt-dlp) → update map (every 5 entries + at end) → aggregate stats printed and logged. A `None` return from `download_track` counts as a failure and the reason is in `logs/download_log_<ts>.log`.

### 6. Sync playlists from YAML (Ya, destructive)
`sync_playlists_from_yaml` (src/yamusic.py:189): read `yamusic.yaml` → index existing playlists by title → create missing ones (`users_playlists_create`) → **clear** each playlist (`delete_tracks_from_playlist`) → select liked tracks where `track artists ∩ playlist artists ≠ ∅` → insert in batches of 50 with the latest revision per batch (API limit workaround).

### 7. Check liked tracks (Ya, destructive)
`check_tracks` (src/yamusic.py:306): fetch each liked short track; if fetch raises, remove it from likes (`users_likes_tracks_remove`). Cleans up dead/region-blocked entries.

## File schemas

| File | Written by | Schema |
|------|-----------|--------|
| `config.yaml` | user | `token: <yandex OAuth>`, optional `ytmusic_download_dir: <path>` (YT output root, default `downloads`; flat; gitignored) |
| `ex_config.yaml` | repo | template for the above |
| `browser.json` | `ytmusicapi browser` | ytmusicapi headers-auth file (live cookies; sensitive) |
| `playlists_map.yaml` | YT menu 5 / user | `Title: {id: PLxxxx, artists: [..]}` |
| `yamusic.yaml` | Ya menu 4 / user | `Title: {kind: 1084, artists: [..]}` |
| `<ytmusic_download_dir>/<P>/track_map_<P>.yaml` | flow 5 | `<video_id>: {video_id, title, artist, file_path, filename, playlist, playlist_id, downloaded_at}` |
| `tracks.txt` | YT menu 4 | TSV: `artist \t title \t videoId` |
| `logs/tracks.json` | flow 1 | `{liked_tracks: [{artist,name}], not_found: [...], errors: [...]}` |
| `logs/music_api_<ts>.log` | src/logger.py | timestamped app log |
| `logs/download_log_<ts>.log` | src/ytmusic.py | download-only log |

All YAML in the repo uses UTF-8 with `allow_unicode=True` (Cyrillic/Georgian titles).

## External dependencies & services

- **Yandex Music** (`yandex-music` 2.2.0): OAuth token; direct connection (no proxy); used for likes, playlists, downloads.
- **YouTube Music** (`ytmusicapi` 1.11.5): browser-cookie auth via `browser.json`; requests routed through SOCKS5 `127.0.0.1:1080`.
- **yt-dlp** (2026.08.19, keep it current) + **ffmpeg**: download & MP3 transcode; same SOCKS5 proxy. Options are passed in code — the Python API does **not** read `~/.config/yt-dlp/config`. YouTube extraction additionally requires a JS runtime (`node` ≥20 or `deno`; default is `deno` only, the code enables both) plus the EJS solver script (`remote_components: ['ejs:github']`, fetched from GitHub once and then cached).

## Known issues / tech debt

1. Hardcoded demo values in `cli.py` (playlist index 1, output `1.yaml`, video id `9zhK-QaEYZY`).
2. `--no-proxy`, `--proxy-port` (src/args.py:21,26) and `--log-file` (src/args.py:39) are parsed but unused; proxy is hardcoded in src/ytmusic.py (lines ~75 and ~499).
3. `YTMusicClient.__init__` performs no lazy init and `main.py` initializes both clients unconditionally — a proxy/network failure blocks startup even for Yandex-only work.
4. `config.yaml` (repo root) holds a plaintext token; security depends entirely on `.gitignore`.
5. `browser.json` with live cookie hashes was committed to git; it is now gitignored and untracked — the exposed cookies should still be rotated (see AGENTS.md Security).
6. No tests, no CI, no non-interactive mode; verification is manual.
7. Broad `try/except` around library calls hides error details (worst: bare `except` in src/yamusic.py:75). yt-dlp failures are an exception now: `download_track` logs the real reason via `YtdlpLogger` (src/ytmusic.py:38) and returns `None`.
8. `get_playlist_artists` (YT) assumes `track["artists"]` is present for every track; malformed entries raise.
9. **yt-dlp must be kept current.** The old build (2026.3.17) failed every YouTube download with a 403 on the media request; updating yt-dlp (2026.08.19) fixed it. When downloads suddenly 403 again, update yt-dlp first. Note: the `download_track` opts (`js_runtimes`, `remote_components`) are required on modern yt-dlp for YouTube extraction.
10. `make clean` removes `__pycache__` only; `downloads/` cleanup is manual.
