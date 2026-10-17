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

`CLI.run()` (src/cli.py:174) loops:

1. **Mode selection**: `1` YouTube Music, `2` Yandex Music, `q/quit/exit` to quit.
2. Inside a mode: type the command number (or alias). `help/?/empty` reprints the menu, `b/back` returns to mode selection, `q/quit/exit` quits.
3. `Ctrl+C` quits gracefully; unexpected exceptions print `Error: ...` and return to the loop.

Quitting does not require confirmation; all commands act immediately on live accounts.

---

## YouTube Music mode

Handler: `CLI.handle_ytmusic_command` (src/cli.py:127).

| # | Aliases | Action | Implementation | Side effects / notes |
|---|---------|--------|----------------|----------------------|
| 1 | `list` | List playlists | `list_playlists` (src/cli.py:56) → `YTMusicClient.get_playlists/print_playlists` (src/ytmusic.py:172,189) | Prints `title: playlistId` (up to 100 playlists) |
| 2 | `artists` | Get playlist artists | src/cli.py:64 → `get_playlist/get_playlist_artists` (src/ytmusic.py:227,235) | **Hardcoded to `playlists[1]`** — effectively a debug command |
| 3 | `tracks` | Count liked tracks not in any playlist | src/cli.py:133 → `get_track_out_playlist` (src/ytmusic.py:334) | Read-only; walks every library playlist (slow on big libraries) |
| 4 | `print` | Write those tracks out | src/cli.py:136 → `print_tracks` (src/ytmusic.py:374) | Writes `logs/tracks.txt` (artist/title/videoId, TSV) |
| 5 | `playlist_map` | Update playlist map | src/cli.py:140 → `update_playlists_map` (src/ytmusic.py:407) | Writes `data/playlists_map_updated.yaml`; excludes `LM`/`SE` |
| 6 | `distribute` | Add out-of-playlist tracks to playlists | src/cli.py:142 → `distribute_tracks` (src/ytmusic.py:391) | **Mutates YouTube playlists** based on `data/playlists_map.yaml` artist match |
| 7 | `download` | Download all playlists | src/cli.py:144 → `download_all_playlists` (src/ytmusic.py:580) | yt-dlp + SOCKS5; writes `<ytmusic_download_dir>/<Playlist>/` and `track_map_*.yaml`; skips `LM`/`SE`; resumable; failed downloads return `None` and log the reason to `logs/download_log_*.log` |
| 8 | `download_track` | Download one track | src/cli.py:146 → `download_track` (src/ytmusic.py:470) | **Hardcoded demo video id `9zhK-QaEYZY`**; saves to `<ytmusic_download_dir>/` |

## Yandex Music mode

Handler: `CLI.handle_yamusic_command` (src/cli.py:154).

| # | Aliases | Action | Implementation | Side effects / notes |
|---|---------|--------|----------------|----------------------|
| 1 | `transfer` | Transfer liked tracks to YouTube Music | `transfer_tracks` (src/cli.py:119) → `move_tracks` (src/cli.py:76) | Asks `y/n`; searches and **likes each track on YouTube**; writes result JSON (`--output`, default `logs/tracks.json`); slow (1 search per track) |
| 2 | `download_playlists` | Download all Yandex playlists | src/cli.py:158 → `download_playlists` (src/yamusic.py:179) | MP3 via Yandex API into `downloads/<Playlist>/`; existing files skipped by filename |
| 3 | `download_liked` | Download liked tracks | src/cli.py:160 → `download_like_tracks` (src/yamusic.py:184) | Into `downloads/Like/` |
| 4 | `playlist_map` | Generate playlist map | src/cli.py:162 → `playlist_map` (src/yamusic.py:85) | Writes `data/temp_playlist_map.yaml` |
| 5 | `p` (note: not `changes`) | Remove broken liked tracks | src/cli.py:164 → `check_tracks` (src/yamusic.py:308) | **Destructive**: unlikes tracks that fail to fetch (per-track error print) |
| 6 | `sync` | Sync playlists from `data/yamusic.yaml` | src/cli.py:166 → `sync_playlists_from_yaml` (src/yamusic.py:191) | **Destructive**: clears each playlist in the YAML, then refills from liked tracks by artist match; creates missing playlists; batches of 50 |

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
| every run | `logs/music_api_<timestamp>.log` |

## Makefile targets

| Target | Effect |
|--------|--------|
| `make run` | `uv run main.py` |
| `make sync` | `uv sync` — creates/updates `.venv` from `uv.lock` |
| `make clean` | Removes `__pycache__` directories (skips `venv/`, `.venv/`) |
