# Command Reference

Full user-facing reference for the interactive CLI, with implementation mapping.
Implementation column points to `file:line` of the handler and the client method it calls.

## Startup

```bash
uv sync                        # first time / after dependency changes
uv run main.py [flags]         # or: make run
```

### Flags (src/args.py)

| Flag | Default | Status | Description |
|------|---------|--------|-------------|
| `--config PATH` | `config/config.yaml` | wired | YAML file with the Yandex token; a bare name is looked up in `config/` (then the legacy repo root) |
| `--output NAME` | `tracks.json` | wired | Transfer result JSON; relative paths are placed under `logs/` (main.py:30) |
| `--no-proxy` | off | **parsed, unused** | Logged but never applied to clients |
| `--proxy-port N` | `1080` | **parsed, unused** | Logged but never applied (`1080` ciadpi / `9150` Tor) |
| `--log-level LEVEL` | `INFO` | wired | `DEBUG`–`CRITICAL` |
| `--log-file NAME` | — | **parsed, unused** | Not passed to `setup_logging` |

## Interaction model

`CLI.run()` (src/cli.py) is a curses-based interactive loop. Every menu is a full-screen arrow-key interface (`_select`):

**Key bindings (all menus):**

| Key | Action |
|-----|--------|
| `↑` / `↓` / `j` / `k` | Move highlight (wraps around) |
| `Enter` | Select highlighted item |
| `1`–`9` (or `0` for 10th) | Quick-pick without navigating |
| `q` / `Esc` | Go back to mode selection (top-level: quit) |

**Flow:**

1. **Mode selection** (curses): YouTube Music / Yandex Music / Buildin AI. `q`/`Esc` exits.
2. Inside a mode (curses sub-menu): navigate, select a command. `q`/`Esc` returns to mode selection.
3. After a command completes, `_pause()` prints `Press Enter to continue...` and waits — results stay on screen.
4. `Ctrl+C` quits gracefully; unexpected exceptions print a red `Error: ...` and return to the menu.

Output colors: cyan (titles/URLs), green (success), yellow (warnings/prompts), red (errors), bold (summaries). Set `NO_COLOR=1` to disable.

Quitting does not require confirmation; all commands act immediately on live accounts.

---

## YouTube Music mode

Handler: `_dispatch_yt(idx)` (src/cli.py). Menu items in `CLI.YT_MENU`.

| # | Action | Implementation | Side effects / notes |
|---|--------|----------------|----------------------|
| 1 | List playlists | `list_playlists` (src/cli.py) → `YTMusicClient.get_playlists` (src/ytmusic.py:172) | Prints `title: playlistId` (up to 100 playlists) |
| 2 | Playlist artists | `get_playlist_artists` (src/cli.py) → `get_playlist/get_playlist_artists` (src/ytmusic.py:227,235) | **Hardcoded to `playlists[1]`** — effectively a debug command |
| 3 | Tracks out of playlist | `_dispatch_yt[2]` → `get_track_out_playlist` (src/ytmusic.py:334) | Read-only; walks every library playlist (slow on big libraries) |
| 4 | Print tracks to file | `_dispatch_yt[3]` → `print_tracks` (src/ytmusic.py:374) | Writes `logs/tracks.txt` (artist/title/videoId, TSV) |
| 5 | Update playlist map | `_dispatch_yt[4]` → `update_playlists_map` (src/ytmusic.py:407) | Writes `data/playlists_map_updated.yaml`; excludes `LM`/`SE` |
| 6 | Distribute tracks | `_dispatch_yt[5]` → `distribute_tracks` (src/ytmusic.py:391) | **Mutates YouTube playlists** based on `data/playlists_map.yaml` artist match |
| 7 | Download all playlists | `_dispatch_yt[6]` → `download_all_playlists` (src/ytmusic.py:580) | yt-dlp + SOCKS5; writes `<ytmusic_download_dir>/<Playlist>/` and `track_map_*.yaml`; skips `LM`/`SE`; resumable; failed downloads return `None` and log the reason to `logs/download_log_*.log` |
| 8 | Download track | `_dispatch_yt[7]` → `download_track` (src/ytmusic.py:470) | **Hardcoded demo video id `9zhK-QaEYZY`**; saves to `<ytmusic_download_dir>/` |

## Yandex Music mode

Handler: `_dispatch_ya(idx)` (src/cli.py). Menu items in `CLI.YA_MENU`.

| # | Action | Implementation | Side effects / notes |
|---|--------|----------------|----------------------|
| 1 | Transfer to YouTube Music | `transfer_tracks` (src/cli.py) → `move_tracks` (src/cli.py) | Asks `y/n`; searches and **likes each track on YouTube**; writes result JSON (`--output`, default `logs/tracks.json`); slow (1 search per track) |
| 2 | Download playlists | `_dispatch_ya[1]` → `download_playlists` (src/yamusic.py:179) | MP3 via Yandex API into `downloads/<Playlist>/`; existing files skipped by filename |
| 3 | Download liked tracks | `_dispatch_ya[2]` → `download_like_tracks` (src/yamusic.py:184) | Into `downloads/Like/` |
| 4 | Get playlist map | `_dispatch_ya[3]` → `playlist_map` (src/yamusic.py:85) | Writes `data/temp_playlist_map.yaml` |
| 5 | Remove broken liked tracks | `_dispatch_ya[4]` → `check_tracks` (src/yamusic.py:308) | **Destructive**: unlikes tracks that fail to fetch (per-track error print) |
| 6 | Sync playlists from YAML | `_dispatch_ya[5]` → `sync_playlists_from_yaml` (src/yamusic.py:191) | **Destructive**: clears each playlist in the YAML, then refills from liked tracks by artist match; creates missing playlists; batches of 50 |

## Buildin AI mode

Handler: `_dispatch_buildin(idx)` (src/cli.py). Menu items in `CLI.BUILDIN_MENU`.
The client is `BuildinClient` (src/buildin.py:130); it speaks MCP Streamable HTTP
and uses the OAuth metadata advertised by the MCP endpoint. Startup performs no
Buildin network calls.

| # | Action | Implementation | Side effects / notes |
|---|--------|----------------|----------------------|
| 1 | Log in | `buildin_login` (src/cli.py) → `BuildinClient.login` (src/buildin.py:164) | Discovers OAuth metadata, dynamically registers a public client, opens the browser, waits up to 300s for a `127.0.0.1` callback, exchanges the code (PKCE S256); writes `config/buildin_tokens.json` (0600) |
| 2 | Status | `buildin_status` (src/cli.py) → `BuildinClient.status` (src/buildin.py:153) | Prints endpoint, token file, authorization state and expiry; no network |
| 3 | List MCP tools | `buildin_tools` (src/cli.py) → `BuildinClient.list_tools` (src/buildin.py:227) | Calls `tools/list`; auto-login if needed; prints names + descriptions |
| 4 | Call MCP tool | `buildin_call_tool` (src/cli.py) → `BuildinClient.call_tool` (src/buildin.py:231) | Prompts for tool name + JSON object; calls `tools/call`; prints text content or raw JSON |
| 5 | Log out | `buildin_logout` (src/cli.py) → `BuildinClient.logout` (src/buildin.py:223) | Deletes the token file and resets the MCP session |
| 6 | Export maps | `buildin_export_maps` (src/cli.py) → `export_maps` (src/buildin_maps.py:53) | Creates/reuses the *Music Library* page + *Playlists* database, then creates/updates one record per playlist (matched by Platform+Title); remote write |
| 7 | Import maps | `buildin_import_maps` (src/cli.py) → `import_maps` / `write_imported_maps` (src/buildin_maps.py:114,138) | Reads the database, prints a per-platform diff, asks `y/n`, then rewrites `data/playlists_map.yaml` and `data/yamusic.yaml` with `.bak` backups; keeps a file whose platform has no records |

Transport details (src/buildin.py:435-556): `initialize` +
`notifications/initialized`, `Mcp-Session-Id`/`MCP-Protocol-Version` headers,
JSON and `text/event-stream` responses, one automatic token refresh on HTTP
401, and one session re-initialization on HTTP 404. `BUILDIN_ACCESS_TOKEN`
overrides the stored access token (useful for scripts/tests).

Buildin map model (src/buildin_maps.py):

- Page `Music Library` (top-level, created on first export) → database `Playlists`.
- Record properties: `Title`, `Platform` (`YouTube`/`Yandex`), `External ID`
  (YouTube playlist id / Yandex kind), `Artists` (one name per line).
- Page/database IDs are cached in `config/buildin_music.json`; delete it to
  force rediscovery.
- Buildin has no record-deletion tool: locally removed playlists are reported
  as orphaned by export and must be deleted in the Buildin UI.

## Direct file outputs

All paths are relative to the repository root (see `src/paths.py`).

| Command | Output |
|---------|--------|
| YT 4 | `logs/tracks.txt` |
| YT 5 | `data/playlists_map_updated.yaml` |
| YT 7 | `<ytmusic_download_dir>/<Playlist>/*.mp3`, `<ytmusic_download_dir>/<Playlist>/track_map_<Playlist>.yaml`, `logs/download_log_*.log`, `logs/music_api_*.log` |
| YT 8 | `<ytmusic_download_dir>/<artist> - <title>.mp3` |
| Ya 1 | `logs/tracks.json` (or `--output`) |
| Ya 2/3 | `downloads/<Playlist>/*.mp3` |
| Ya 4 | `data/temp_playlist_map.yaml` |
| Buildin 1 | `config/buildin_tokens.json` |
| Buildin 6 | Buildin page/database; `config/buildin_music.json` (ID cache) |
| Buildin 7 | `data/playlists_map.yaml`, `data/yamusic.yaml` (+ `.bak` copies) |
| every run | `logs/music_api_<timestamp>.log` |

## Makefile targets

| Target | Effect |
|--------|--------|
| `make run` | `uv run main.py` |
| `make sync` | `uv sync` — creates/updates `.venv` from `uv.lock` |
| `make clean` | Removes `__pycache__` directories (skips `venv/`, `.venv/`) |
