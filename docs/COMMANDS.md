# Command Reference

Full user-facing reference for the interactive CLI, with implementation mapping.
Implementation column points to `file:line` of the handler and the client method it calls.

## Startup

```bash
source venv/bin/activate
python3 main.py [flags]        # or: make run
```

### Flags (src/args.py)

| Flag | Default | Status | Description |
|------|---------|--------|-------------|
| `--config PATH` | `config.yaml` | wired | YAML file with the Yandex token |
| `--output NAME` | `tracks.json` | wired | Transfer result JSON; relative paths are placed under `logs/` (main.py:29) |
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
| 1 | `list` | List playlists | `list_playlists` (src/cli.py:56) → `YTMusicClient.get_playlists/print_playlists` (src/ytmusic.py:136,153) | Prints `title: playlistId` (up to 100 playlists) |
| 2 | `artists` | Get playlist artists | src/cli.py:64 → `get_playlist/get_playlist_artists` (src/ytmusic.py:191,199) | **Hardcoded to `playlists[1]`** — effectively a debug command |
| 3 | `tracks` | Count liked tracks not in any playlist | src/cli.py:133 → `get_track_out_playlist` (src/ytmusic.py:298) | Read-only; walks every library playlist (slow on big libraries) |
| 4 | `print` | Write those tracks out | src/cli.py:136 → `print_tracks` (src/ytmusic.py:338) | Writes `tracks.txt` (artist/title/videoId, TSV) in CWD |
| 5 | `playlist_map` | Update playlist map | src/cli.py:140 → `update_playlists_map` (src/ytmusic.py:370) | **Writes `1.yaml` (hardcoded)**; excludes `LM`/`SE` |
| 6 | `distribute` | Add out-of-playlist tracks to playlists | src/cli.py:142 → `distribute_tracks` (src/ytmusic.py:354) | **Mutates YouTube playlists** based on `playlists_map.yaml` artist match |
| 7 | `download` | Download all playlists | src/cli.py:144 → `download_all_playlists` (src/ytmusic.py:524) | yt-dlp + SOCKS5; writes `downloads/<Playlist>/` and `track_map_*.yaml`; skips `LM`/`SE`; resumable |
| 8 | `download_track` | Download one track | src/cli.py:146 → `download_track` (src/ytmusic.py:431) | **Hardcoded demo video id `9zhK-QaEYZY`**; saves to `downloads/` |

## Yandex Music mode

Handler: `CLI.handle_yamusic_command` (src/cli.py:154).

| # | Aliases | Action | Implementation | Side effects / notes |
|---|---------|--------|----------------|----------------------|
| 1 | `transfer` | Transfer liked tracks to YouTube Music | `transfer_tracks` (src/cli.py:119) → `move_tracks` (src/cli.py:76) | Asks `y/n`; searches and **likes each track on YouTube**; writes result JSON (`--output`, default `logs/tracks.json`); slow (1 search per track) |
| 2 | `download_playlists` | Download all Yandex playlists | src/cli.py:158 → `download_playlists` (src/yamusic.py:177) | MP3 via Yandex API into `downloads/<Playlist>/`; existing files skipped by filename |
| 3 | `download_liked` | Download liked tracks | src/cli.py:160 → `download_like_tracks` (src/yamusic.py:182) | Into `downloads/Like/` |
| 4 | `playlist_map` | Generate playlist map | src/cli.py:162 → `playlist_map` (src/yamusic.py:84) | **Writes `temp_playlist_map.yaml`** in CWD |
| 5 | `p` (note: not `changes`) | Remove broken liked tracks | src/cli.py:164 → `check_tracks` (src/yamusic.py:306) | **Destructive**: unlikes tracks that fail to fetch (per-track error print) |
| 6 | `sync` | Sync playlists from `yamusic.yaml` | src/cli.py:166 → `sync_playlists_from_yaml` (src/yamusic.py:189) | **Destructive**: clears each playlist in the YAML, then refills from liked tracks by artist match; creates missing playlists; batches of 50 |

## Direct file outputs

| Command | Output |
|---------|--------|
| YT 4 | `tracks.txt` |
| YT 5 | `1.yaml` |
| YT 7 | `downloads/<Playlist>/*.mp3`, `downloads/<Playlist>/track_map_<Playlist>.yaml`, `logs/download_log_*.log`, `logs/music_api_*.log` |
| YT 8 | `downloads/<artist> - <title>.mp3` |
| Ya 1 | `logs/tracks.json` (or `--output`) |
| Ya 2/3 | `downloads/<Playlist>/*.mp3` |
| Ya 4 | `temp_playlist_map.yaml` |
| every run | `logs/music_api_<timestamp>.log` |

## Makefile targets

| Target | Effect |
|--------|--------|
| `make run` | `python3 main.py` |
| `make venv` | Creates `venv/` |
| `make requirements` | `pip install -r requirements.txt` |
| `make clean` | Removes `__pycache__` directories |
