# Refactoring Plan — `refactor/project` branch

Base: `main` @ `9fd2df1`. All changes are non-destructive to live data; every commit leaves the app runnable.

## Phase 1 — Blockers & Critical Bugs

### 1.1 `src/ytmusic.py` — remove console logging (blocker)
- Remove `console_handler` (lines 24–26, 31). The module logger should only have `file_handler`.
- `file_logger.propagate = False` stays (prevents double-logging to root).
- Move the import-time side effect (log file creation) into a private `_setup_download_logger()` called from `__init__` instead of module level. This removes the import-time file creation.
- Move `import sys`, `from contextlib import contextmanager` to top of file (currently inside `download_track` at line 483–484).
- Fix `from src import paths` → `from . import paths` (line 12); fix `from src.track import Track` → `from .track import Track` (line 68) and move to top.

### 1.2 `src/cli.py` — `move_tracks` bare `open(out_path)` (blocker from review)
- `main.py` only resolves `--output` when it's not absolute; absolute `--output` bypasses `paths.resolve()`.
- Fix: in `main.py`, always run `args.output` through `paths.resolve(args.output)` (remove the `is_absolute` branch). This covers both cases.

### 1.3 `src/yamusic.py` — bare `except:` (line 76)
- Change to `except Exception:` with a `file_logger` or `print` warning.

## Phase 2 — Code Style & Cleanup

### 2.1 `src/cli.py`
- Move `YT_MENU`/`YA_MENU`/`BUILDIN_MENU` to top of class (before `_select`).
- Add type hints to all methods: `_dispatch_yt(self, idx: int) -> None`, etc.
- Remove dead code in `_select`: the `key == 48 and n >= 10` block (line 87–89) — no menu has 10+ items.
- Add `# lazy import: curses is only needed when the menu actually runs` comment above `import curses`.
- Add type hint `stdscr: "curses._CursesFile"` to `_run`.
- Add `assert 0 <= idx < len(cmds)` at top of each `_dispatch_*`.
- Rename `transfer_tracks` confirm to use a shared `_confirm(prompt: str) -> bool` helper (used by both `transfer_tracks` and `buildin_import_maps`).
- Add `(destructive)` suffix to `YA_MENU[4]` and `YA_MENU[5]` labels.
- Add `if len(playlists) < 2:` guard in `get_playlist_artists`.
- Rename `YT_MENU[7]` label to `"Download track (demo)"`.
- Fix double-newline in `except Exception` print: `color.red(f"\nError: {e}")` (remove trailing `\n`).

### 2.2 `src/yamusic.py`
- Add docstring `# DEMO: not wired to CLI` to `add_tracks_to_playlist` and `create_playlist`.
- Fix `from . import paths` — already correct. Remove unused `Artist` import (line 3).
- Fix `playlist_map`: `playlist["title"]` and `playlist["kind"]` — `Playlist` is a `yandex_music` object, not a dict; should be `playlist.title` and `playlist.kind` (matches `print_playlists` on line 83). This is a real bug.

### 2.3 `src/ytmusic.py`
- Remove unused `Union` from typing import (check usage).
- `print_playlists` (line 189–191): fix nested quote issue `playlist["title"]` inside f-string with double quotes — use single quotes inside.
- `download_all_playlists`: extract the `excluded_ids = ["LM", "SE"]` into a module-level constant `EXCLUDED_PLAYLIST_IDS = frozenset({"LM", "SE"})`.
- `get_track_out_playlist`: add `EXCLUDED_PLAYLIST_IDS` usage.
- `update_playlists_map`: same.
- `download_all_playlists`: same.

### 2.4 `src/paths.py`
- Replace `print(...)` in `_with_legacy` with `logging.getLogger(__name__).warning(...)`.

### 2.5 `src/logger.py`
- Replace `logging.info(...)` at lines 26–28 with `logger.info(...)` (use the local `logger` variable, not the module-level `logging` shortcut — they're equivalent here but the intent is clearer).

### 2.6 `src/__init__.py`
- Add `MapSyncError` to imports and `__all__`.
- Add `Track` to imports and `__all__` (it's the shared type).

## Phase 3 — Structure & Docs

### 3.1 `README.md`
- Add `src/color.py` to the repository layout section.

### 3.2 `docs/ARCHITECTURE.md`
- Add `BUILDIN_TOKENS_FILE`, `BUILDIN_STATE_FILE`, `EXAMPLE_CONFIG_FILE` to the paths table.
- Fix any `file:line` references that shifted after Phase 1/2 changes.

### 3.3 `AGENTS.md`
- Fix `file:line` references in Gotchas that shifted after Phase 1/2 changes.
- Update the `/test` command description in the OpenCode section to show the actual import smoke check.

## Phase 4 — Commit Strategy

| Commit | Phase | Contents |
|--------|-------|----------|
| 1 | 1.1 | `src/ytmusic.py`: remove console logger, lazy logger init, fix imports |
| 2 | 1.2 | `main.py`: always resolve `--output` through `paths.resolve()` |
| 3 | 1.3 | `src/yamusic.py`: bare `except` → `except Exception` |
| 4 | 2.1 | `src/cli.py`: all style/cleanup changes |
| 5 | 2.2 | `src/yamusic.py`: demo markers, unused import, `playlist_map` bug fix |
| 6 | 2.3 | `src/ytmusic.py`: EXCLUDED_PLAYLIST_IDS constant, quote fix, unused import |
| 7 | 2.4+2.5 | `src/paths.py` + `src/logger.py`: print→log, logging.info→logger.info |
| 8 | 2.6 | `src/__init__.py`: add `MapSyncError`, `Track` exports |
| 9 | 3.1–3.3 | Docs: README, ARCHITECTURE, AGENTS.md updates |

Each commit runs the import smoke check:
```bash
uv run python -c "from src.cli import CLI; from src import color, paths, track; from src.yamusic import YaMusicHandle; from src.ytmusic import YTMusicClient; from src.buildin import BuildinClient; from src.buildin_maps import export_maps, import_maps; from src.logger import setup_logging; from src.args import parse_args; print('OK')"
```
