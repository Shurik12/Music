# Command Reference

Full user-facing reference for the Typer CLI. The root `music` command mounts
three sub-apps — `ytmusic`, `yamusic`, `buildin` — each with its own commands.
Global options are passed on the command line (before or after the sub-command;
Typer's callback runs first either way).

## Startup

```bash
uv sync                        # first time / after dependency changes
uv run main.py [GLOBAL-OPTS] COMMAND [ARGS]...
uv run main.py [GLOBAL-OPTS] COMMAND --help   # per-command help
```

### Global flags (src/cli.py callback)

| Flag | Default | Status | Description |
|------|---------|--------|-------------|
| `--config PATH` / `-c` | `config/config.yaml` | wired | YAML file with the Yandex token; a bare name is looked up in `config/` (then the legacy repo root) |
| `--output NAME` / `-o` | — (default `logs/tracks.json` for `yamusic transfer`) | wired | Where `yamusic transfer` writes its JSON report; relative paths are rebased into `logs/` |
| `--no-proxy` | off | **parsed, unused** | Logged but never applied to clients |
| `--proxy-port N` | `1080` | **parsed, unused** | Logged but never applied (`1080` ciadpi / `9150` Tor) |
| `--log-level LEVEL` | `INFO` | wired | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `--log-file NAME` | — | **parsed, unused** | Not passed to `setup_logging` |

### Destructive commands

Destructive commands (`yamusic transfer`, `yamusic check-tracks`,
`yamusic sync-from-yaml`, `buildin import-maps`) prompt for `y/n` confirmation
unless `--yes` / `-y` is passed.

---

## ytmusic sub-app

Handler module: `src/cli_ytmusic.py`.

| Command | Action | Implementation | Side effects / notes |
|---------|--------|----------------|----------------------|
| `list-playlists` | List all user playlists | `YTMusicClient.get_playlists/print_playlists` (src/ytmusic.py:172,189) | Prints `title: playlistId` (up to 100) |
| `playlist-artists [-i N]` | Print artists in playlist at index N | `get_playlist/get_playlist_artists` (src/ytmusic.py:227,235) | Index `0`-based; default `1` |
| `tracks-out-of-playlist` | Count liked tracks not in any playlist | `get_track_out_playlist` (src/ytmusic.py:334) | Read-only; walks every library playlist |
| `print-tracks` | Write those tracks to a file | `print_tracks` (src/ytmusic.py:374) | Writes `logs/tracks.txt` (artist/title/videoId, TSV) |
| `update-map [-o PATH]` | Regenerate the YT playlist map | `update_playlists_map` (src/ytmusic.py:407) | Writes `data/playlists_map_updated.yaml`; excludes `LM`/`SE` |
| `distribute` | Add out-of-playlist tracks to playlists | `distribute_tracks` (src/ytmusic.py:391) | **Mutates YouTube playlists** based on `data/playlists_map.yaml` artist match |
| `download-all [-f FMT] [-q QUAL] [--no-skip] [--limit N]` | Download every user playlist | `download_all_playlists` (src/ytmusic.py:580) | yt-dlp + SOCKS5; writes `<ytmusic_download_dir>/<Playlist>/` and `track_map_*.yaml`; skips `LM`/`SE`; resumable |
| `download-track -v VIDEO_ID [-q QUAL] [-f FMT] [--quiet]` | Download one track | `download_track` (src/ytmusic.py:470) | Saves to `<ytmusic_download_dir>/`; returns the saved path on success |

## yamusic sub-app

Handler module: `src/cli_yamusic.py`.

| Command | Action | Implementation | Side effects / notes |
|---------|--------|----------------|----------------------|
| `transfer [-o PATH] [-y]` | Transfer liked tracks to YouTube Music | `export_liked_tracks` → `import_liked_tracks` (src/yamusic.py:16, src/ytmusic.py:120) | Searches and **likes each track on YouTube**; writes result JSON (default `logs/tracks.json`); destructive |
| `download-playlists` | Download all Yandex playlists | `download_playlists` (src/yamusic.py:179) | MP3 via Yandex API into `downloads/<Playlist>/` |
| `download-liked` | Download liked tracks as one folder | `download_like_tracks` (src/yamusic.py:184) | Into `downloads/Like/` |
| `playlist-map [-o PATH]` | Generate the Yandex playlist map | `playlist_map` (src/yamusic.py:85) | Writes `data/temp_playlist_map.yaml` |
| `check-tracks [-y]` | Remove broken liked tracks | `check_tracks` (src/yamusic.py:308) | **Destructive**: unlikes tracks that fail to fetch |
| `sync-from-yaml [-f FILE] [-y]` | Clear and repopulate Yandex playlists from YAML | `sync_playlists_from_yaml` (src/yamusic.py:191) | **Destructive**: clears each playlist in the YAML, then refills from liked tracks by artist match; batches of 50 |

## buildin sub-app

Handler module: `src/cli_buildin.py`. The client is `BuildinClient`
(src/buildin.py:130); it speaks MCP Streamable HTTP and uses the OAuth metadata
advertised by the MCP endpoint. Startup performs no Buildin network calls.

| Command | Action | Implementation | Side effects / notes |
|---------|--------|----------------|----------------------|
| `login` | Authorize with Buildin | `BuildinClient.login` (src/buildin.py:164) | Discovers OAuth metadata, dynamically registers a public client, opens the browser, waits up to 300s for a `127.0.0.1` callback, exchanges the code (PKCE S256); writes `config/buildin_tokens.json` (0600) |
| `status` | Show auth state | `BuildinClient.status` (src/buildin.py:153) | Prints endpoint, token file, authorization state and expiry; no network |
| `tools` | List MCP tools | `BuildinClient.list_tools` (src/buildin.py:227) | Calls `tools/list`; auto-login if needed |
| `call -t NAME [-a JSON]` | Call an MCP tool | `BuildinClient.call_tool` (src/buildin.py:231) | Takes a `--tool` name and a `--args` JSON object; prints text content or raw JSON |
| `logout` | Forget tokens | `BuildinClient.logout` (src/buildin.py:223) | Deletes the token file and resets the MCP session |
| `export-maps` | Export playlist maps to Buildin | `export_maps` (src/buildin_maps.py:53) | Creates/reuses the *Music Library* page + *Playlists* database, then creates/updates one record per playlist |
| `import-maps [-y]` | Import playlist maps from Buildin | `import_maps` / `write_imported_maps` (src/buildin_maps.py:114,138) | Reads the database, prints a per-platform diff, then rewrites `data/playlists_map.yaml` and `data/yamusic.yaml` with `.bak` backups |

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
| `ytmusic print-tracks` | `logs/tracks.txt` |
| `ytmusic update-map` | `data/playlists_map_updated.yaml` |
| `ytmusic download-all` | `<ytmusic_download_dir>/<Playlist>/*.mp3`, `<ytmusic_download_dir>/<Playlist>/track_map_<Playlist>.yaml`, `logs/download_log_*.log`, `logs/music_api_*.log` |
| `ytmusic download-track` | `<ytmusic_download_dir>/<artist> - <title>.mp3` |
| `yamusic transfer` | `logs/tracks.json` (or `--output`) |
| `yamusic download-playlists` / `yamusic download-liked` | `downloads/<Playlist>/*.mp3` |
| `yamusic playlist-map` | `data/temp_playlist_map.yaml` |
| `buildin login` | `config/buildin_tokens.json` |
| `buildin export-maps` | Buildin page/database; `config/buildin_music.json` (ID cache) |
| `buildin import-maps` | `data/playlists_map.yaml`, `data/yamusic.yaml` (+ `.bak` copies) |
| every run | `logs/music_api_<timestamp>.log` |

## Makefile targets

| Target | Effect |
|--------|--------|
| `make run` | `uv run main.py` |
| `make sync` | `uv sync` — creates/updates `.venv` from `uv.lock` |
| `make clean` | Removes `__pycache__` directories (skips `venv/`, `.venv/`) |
