# Music

Personal CLI tool for managing a music library between **Yandex Music** and **YouTube Music**, plus bulk downloading of playlists and liked tracks to local MP3 files.

It can:

- Transfer liked tracks from Yandex Music to YouTube Music (search + like).
- Keep YouTube Music playlists organized by artist using a YAML map (`data/playlists_map.yaml`).
- Keep Yandex Music playlists organized by artist using a YAML map (`data/yamusic.yaml`).
- Download YouTube Music playlists as MP3 via [yt-dlp](https://github.com/yt-dlp/yt-dlp).
- Download Yandex Music playlists / liked tracks as MP3 via the `yandex-music` API.
- Track already-downloaded tracks per playlist with `track_map_*.yaml` files (resumable downloads).

## Requirements

- Linux, Python **3.12+** (the code uses PEP 701 f-strings with nested quotes)
- `ffmpeg` (required by yt-dlp for MP3 conversion): `sudo apt install ffmpeg`
- [uv](https://docs.astral.sh/uv/) for dependency management (`uv sync`)
- Node.js **≥20** (or deno) — yt-dlp needs a JS runtime for YouTube extraction; the EJS solver script is fetched from GitHub on first use and then cached
- A local SOCKS5 proxy on `127.0.0.1:1080` (e.g. ciadpi; Tor would be `9150`). The YouTube Music API client and yt-dlp are hardcoded to use it — see the [known issues](docs/ARCHITECTURE.md).
- Accounts / credentials:
  - Yandex Music OAuth token
  - YouTube Music browser auth (`config/browser.json`, export with `ytmusicapi browser --file config/browser.json`)

Dependencies are managed with [uv](https://docs.astral.sh/uv/) — declared in `pyproject.toml`, pinned in `uv.lock`:

```
yandex-music  ytmusicapi  tqdm  pyyaml  requests[socks]  yt-dlp
```

## Setup

```bash
cd ~/git/Music

# 1. Dependencies (creates .venv and installs from uv.lock)
uv sync

# 2. Configuration
cp config/ex_config.yaml config/config.yaml   # config.yaml is gitignored
$EDITOR config/config.yaml                     # Yandex Music token (+ optional ytmusic_download_dir)

# 3. YouTube Music auth (config/browser.json)
uv run ytmusicapi browser --file config/browser.json
```

`config/config.yaml` is a flat YAML file:

```yaml
token: "your_yandex_token"
ytmusic_download_dir: downloads   # optional; where YouTube Music MP3s are saved
```

### Re-exporting browser.json

YouTube auth expires after a while (Google session cookies go stale). Symptoms: empty results from account methods, or the startup warning. To refresh `config/browser.json`:

1. Log in to https://music.youtube.com and open DevTools (`F12`) → **Network** tab.
2. Type `browse` in the filter box and reload the page.
3. Right-click a `browse?prettyPrint=false` **POST** request → **Copy** → **Copy as fetch (Node.js)**.
   - Use the **(Node.js)** variant — plain *Copy as fetch* omits the `Cookie` header, which is exactly what breaks the export.
4. Run the setup and paste:

   ```bash
   cd ~/git/Music && uv run ytmusicapi browser --file config/browser.json
   # paste the copied block, then press Ctrl+D
   ```

   File-based alternative: save the copied block to `/tmp/yt_headers.txt`, then

   ```bash
   uv run python -c "from ytmusicapi.setup import setup; setup('config/browser.json', open('/tmp/yt_headers.txt').read())"
   ```

5. Sanity check: the pasted block must include a line containing `cookie:` with `__Secure-3PAPISID`. `ytmusicapi` silently drops pasted lines that don't contain `': '` — a missing cookie line is the most common export failure.

`config/browser.json` holds live session cookies — never commit it.

## Usage

```bash
uv run main.py             # or: make run
```

The tool is an interactive menu. First pick an API mode, then issue commands.

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
src/track.py            Track named tuple (artist, name)
src/paths.py            Project-wide path constants (anchored to the repo root)
src/config.py           YAML config loader
src/args.py             argparse definitions
src/logger.py           Logging setup (console + file)
config/config.yaml      Yandex token + settings (gitignored)
config/ex_config.yaml   Example config template
config/browser.json     YouTube Music browser auth (sensitive!, gitignored)
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

## Logging & outputs

- `logs/music_api_<timestamp>.log` — main run log (created by `src/logger.py`).
- `logs/download_log_<timestamp>.log` — download log (created by `src/ytmusic.py`).
- `logs/tracks.json` — transfer results (liked / not found / errors), when using the default `--output`.
- `logs/tracks.txt` — TSV dump written by YT menu 4.

All paths are anchored to the repository root, so the CLI can be launched from any directory (e.g. `uv run --project ~/git/Music ~/git/Music/main.py`).

## Troubleshooting

- **"missing 1 required positional argument: 'id'"** — a Yandex liked track with a broken artist reference; the exporter skips such tracks by design.
- **YouTube Music returns empty results (no error)** — `config/browser.json` has expired: account endpoints silently return the logged-out view. The app warns about this at startup. Re-export it (see [Re-exporting browser.json](#re-exporting-browserjson)).
- **`Your cookie is missing the required value __Secure-3PAPISID`** — the exported headers didn't include the `cookie` header. Re-copy using **Copy as fetch (Node.js)** or *Copy request headers* — plain *Copy as fetch* strips cookies — and make sure the paste contains a line starting with `cookie:` (details in [Re-exporting browser.json](#re-exporting-browserjson)).
- **All YouTube requests fail / time out** — the tool expects a SOCKS5 proxy on `127.0.0.1:1080`. Start ciadpi (or edit the proxy in `src/ytmusic.py`).
- **Downloads fail with HTTP 403 errors** — usually an outdated yt-dlp (the 2026.3.17 build failed every download; 2026.08.19 works). Update it: `uv lock --upgrade-package yt-dlp && uv sync`. Recent yt-dlp versions need node ≥20 (or deno) and fetch the EJS solver from GitHub on first run. The exact yt-dlp error is logged to `logs/download_log_<timestamp>.log` (see *Known issues* in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **`config/config.yaml` not found** — you must create it from `config/ex_config.yaml`; it is intentionally gitignored.
- **MP3 conversion fails** — install `ffmpeg`.

## Security notes

- `config/config.yaml` (real token) and `.venv/` are gitignored — keep it that way.
- `config/browser.json` contains live YouTube auth cookies. It is now gitignored and untracked, but it was committed previously — if this repo was ever pushed anywhere, rotate the cookies (re-run `ytmusicapi browser --file config/browser.json`) and avoid re-adding the file.
- `downloads/`, `logs/` and `__pycache__/` are generated and gitignored.

## More documentation

- [AGENTS.md](AGENTS.md) — entry point for AI agents / contributors (quick start, conventions, gotchas)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data flows, file schemas
- [docs/COMMANDS.md](docs/COMMANDS.md) — full CLI command reference with implementation mapping

## License

See [LICENSE](LICENSE).
