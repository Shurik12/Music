import json
import os
from datetime import datetime

from . import color
from .yamusic import YaMusicHandle
from .ytmusic import YTMusicClient
from .buildin import BuildinClient, BuildinError
from .buildin_maps import MapSyncError, export_maps, import_maps, write_imported_maps

class CLI:
    def __init__(self, yamusic: YaMusicHandle, ytmusic: YTMusicClient, buildin: BuildinClient, args):
        self.yamusic = yamusic
        self.ytmusic = ytmusic
        self.buildin = buildin
        self.args = args
        self.running = True
        self.mode = None  # 'ytmusic', 'yamusic' or 'buildin'
        
    @staticmethod
    def _select(title: str, items: list[str],
               back_label: str = "Back") -> int:
        """Interactive curses menu. Returns 0-based index, or -1 for back/quit."""
        import curses

        footer = [f"{back_label}  ·  q / esc to {back_label.lower()}",
                  "↑/↓ move  ·  enter select  ·  1-N quick pick"]

        def _run(stdscr) -> int:
            curses.curs_set(0)
            stdscr.keypad(True)
            curses.use_default_colors()
            #  1=title  2=separator  3=selected-item  4=footer
            curses.init_pair(1, curses.COLOR_CYAN,   -1)
            curses.init_pair(2, curses.COLOR_WHITE,  -1)
            curses.init_pair(3, curses.COLOR_GREEN,  -1)
            curses.init_pair(4, curses.COLOR_YELLOW, -1)

            selected = [0]
            n = len(items)

            def frame() -> None:
                stdscr.erase()
                max_y, max_x = stdscr.getmaxyx()
                stdscr.addnstr(0, 2, title, max_x - 4,
                               curses.A_BOLD | curses.color_pair(1))
                stdscr.addnstr(1, 2, "─" * (max_x - 4), max_x - 4,
                               curses.color_pair(2))
                for i, label in enumerate(items):
                    y = 2 + i
                    if y >= max_y:
                        break
                    if i == selected[0]:
                        stdscr.addnstr(y, 2, "▸ " + label, max_x - 4,
                                       curses.A_REVERSE | curses.A_BOLD
                                       | curses.color_pair(3))
                    else:
                        stdscr.addnstr(y, 2, "  " + label, max_x - 4)
                fy = 2 + n + 1
                for line in footer:
                    if fy >= max_y:
                        break
                    stdscr.addnstr(fy, 2, line, max_x - 4, curses.color_pair(4))
                    fy += 1
                stdscr.refresh()

            frame()

            while True:
                key = stdscr.getch()
                if key in (ord('q'), ord('Q'), 27):
                    selected[0] = -1
                    break
                elif key in (curses.KEY_UP, ord('k')):
                    selected[0] = (selected[0] - 1) % n
                    frame()
                elif key in (curses.KEY_DOWN, ord('j')):
                    selected[0] = (selected[0] + 1) % n
                    frame()
                elif key in (curses.KEY_ENTER, 10, 13):
                    break
                elif 49 <= key <= 57:  # '1'..'9'
                    idx = key - 49
                    if idx < n:
                        selected[0] = idx
                        break
                elif key == 48 and n >= 10:  # '0'
                    selected[0] = 0
                    break
            return selected[0]

        return curses.wrapper(_run)
    
    def list_playlists(self):
        """List all playlists"""
        try:
            playlists = self.ytmusic.get_playlists()
            for p in playlists:
                print(f"  {color.cyan(p['title'])}: {p['playlistId']}")
        except Exception as e:
            print(color.red(f"Error listing playlists: {e}"))
    
    def get_playlist_artists(self):
        """Get artists from a specific playlist"""
        try:
            playlists = self.ytmusic.get_playlists()
            playlist = self.ytmusic.get_playlist(playlists[1]["playlistId"])
            artists = self.ytmusic.get_playlist_artists(playlist)
            print(color.cyan_bold(playlist["title"]))
            for artist in artists:
                print(f"  {artist}")
        except Exception as e:
            print(color.red(f"Error getting playlist artists: {e}"))

    def move_tracks(self, out_path: str) -> None:
        data = {
            'liked_tracks': [],
            'not_found': [],
            'errors': [],
        }
        
        print(color.cyan('Exporting liked tracks from Yandex Music...'))
        tracks = self.yamusic.export_liked_tracks()
        tracks.reverse()

        for track in tracks:
            data['liked_tracks'].append({
                'artist': track.artist,
                'name': track.name
            })

        print(color.cyan('Importing liked tracks to YouTube Music...'))
        not_found, errors = self.ytmusic.import_liked_tracks(tracks)

        for track in not_found:
            data['not_found'].append({
                'artist': track.artist,
                'name': track.name
            })
            print(color.yellow(f'  Not found: {track.artist} - {track.name}'))

        for track in errors:
            data['errors'].append({
                'artist': track.artist,
                'name': track.name
            })
            print(color.red(f'  Error: {track.artist} - {track.name}'))

        print(color.bold(f'\nSummary: {len(tracks)} total tracks'))
        print(color.green(f'  Successfully imported: {len(tracks) - len(not_found) - len(errors)}'))
        print(color.yellow(f'  Not found: {len(not_found)}'))
        print(color.red(f'  Errors: {len(errors)}'))

        str_data = json.dumps(data, indent=2, ensure_ascii=False)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(str_data)
    
    def transfer_tracks(self):
        """Transfer tracks from Yandex Music to YouTube Music"""
        confirm = input("\nThis will transfer liked tracks from Yandex Music to YouTube Music. Continue? (y/n): ")
        if confirm.lower() in ['y', 'yes']:
            self.move_tracks(self.args.output)
        else:
            print("Transfer cancelled.")
    
    def buildin_ensure_login(self) -> bool:
        """Log in on demand before running a command that needs Buildin auth."""
        if self.buildin.is_authorized():
            return True
        print(color.yellow("Buildin authorization is required for this command."))
        return self.buildin_login()
    
    def buildin_login(self) -> bool:
        try:
            data = self.buildin.login()
        except BuildinError as e:
            print(color.red(f"Buildin login failed: {e}"))
            return False
        except Exception as e:
            print(color.red(f"Buildin login failed: {type(e).__name__}: {e}"))
            return False

        expires_at = data.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(color.green(f"Logged in to Buildin MCP. Token expires at {expires} (auto-refreshed)."))
        else:
            print(color.green("Logged in to Buildin MCP."))
        return True
    
    def buildin_status(self):
        status = self.buildin.status()
        print(f"  MCP endpoint: {color.cyan(status['mcp_url'])}")
        print(f"  Token file:   {status['token_file']}")
        if not status["authorized"]:
            print(f"  Status:       {color.red('not authorized')} (run Log in first)")
            return
        if os.environ.get("BUILDIN_ACCESS_TOKEN"):
            print(f"  Status:       {color.green('authorized')} via BUILDIN_ACCESS_TOKEN")
            return
        expires_at = status.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  Status:       {color.green('authorized')} (token expires at {expires})")
        else:
            print(f"  Status:       {color.green('authorized')}")
    
    def buildin_tools(self):
        if not self.buildin_ensure_login():
            return
        try:
            tools = self.buildin.list_tools()
        except BuildinError as e:
            print(color.red(f"Could not list Buildin tools: {e}"))
            return

        if not tools:
            print(color.yellow("The Buildin MCP server exposes no tools."))
            return

        print(color.bold(f"\n{len(tools)} Buildin MCP tools:"))
        for tool in tools:
            name = color.cyan(tool.get("name", "?"))
            description = " ".join((tool.get("description") or "").split())
            if description:
                print(f"  {name}  {description[:140]}")
            else:
                print(f"  {name}")
    
    def buildin_call_tool(self):
        if not self.buildin_ensure_login():
            return
        
        name = input("Tool name: ").strip()
        if not name:
            print("No tool name given.")
            return
        
        raw_arguments = input("Arguments as JSON (empty for {}): ").strip()
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError as e:
            print(f"Invalid JSON arguments: {e}")
            return
        if not isinstance(arguments, dict):
            print("Arguments must be a JSON object.")
            return
        
        try:
            result = self.buildin.call_tool(name, arguments)
        except BuildinError as e:
            print(color.red(f"Buildin tool call failed: {e}"))
            return

        self.print_tool_result(result)
    
    def print_tool_result(self, result):
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    print(item.get("text", ""))
                else:
                    print(json.dumps(item, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        
        if isinstance(result, dict) and result.get("isError"):
            print("(the tool reported an error)")
    
    def buildin_logout(self):
        self.buildin.logout()
        print(color.green("Buildin tokens removed."))
    
    def buildin_export_maps(self):
        if not self.buildin_ensure_login():
            return
        print(color.cyan("Exporting local playlist maps to Buildin..."))
        try:
            result = export_maps(self.buildin)
        except MapSyncError as e:
            print(color.red(f"Buildin export failed: {e}"))
            return

        print(f"  Page:     {color.cyan(result['page_id'])}")
        print(f"  Database: {color.cyan(result['database_id'])}")
        print(
            f"  Records:  {color.green(str(result['created']))} created, "
            f"{color.yellow(str(result['updated']))} updated, "
            f"{result['unchanged']} unchanged (total {result['total']})"
        )
        if result["orphaned"]:
            print(color.yellow("\nOrphaned in Buildin (delete manually in the UI):"))
            for platform, title in result["orphaned"]:
                print(f"  {color.yellow(platform)}: {title}")
    
    def buildin_import_maps(self):
        if not self.buildin_ensure_login():
            return
        print(color.cyan("Reading playlist maps from Buildin..."))
        try:
            result = import_maps(self.buildin)
        except MapSyncError as e:
            print(color.red(f"Buildin import failed: {e}"))
            return

        print(
            f"  Records: {result['records']}  |  "
            f"YouTube: {color.cyan(str(len(result['youtube'])))}  |  "
            f"Yandex: {color.cyan(str(len(result['yandex'])))}"
        )
        for platform, key in (("YouTube", "youtube_diff"), ("Yandex", "yandex_diff")):
            diff = result[key]
            print(
                f"  {platform} changes: "
                f"+{color.green(str(len(diff['added'])))} "
                f"-{color.red(str(len(diff['removed'])))} "
                f"~{color.yellow(str(len(diff['changed'])))}"
            )
            for label in ("added", "removed", "changed"):
                colors = {"added": color.green, "removed": color.red, "changed": color.yellow}
                c = colors[label]
                values = diff[label]
                for value in values[:10]:
                    print(f"    {c(label)}: {value}")
                if len(values) > 10:
                    print(f"    ... {len(values) - 10} more {label}")

        if not result["youtube"]:
            print(color.yellow("No YouTube records — data/playlists_map.yaml will be kept."))
        if not result["yandex"]:
            print(color.yellow("No Yandex records — data/yamusic.yaml will be kept."))
        if not result["youtube"] and not result["yandex"]:
            return

        confirm = input(color.bold("\nOverwrite local YAML maps with the Buildin data? (y/n): "))
        if confirm.strip().lower() not in ("y", "yes"):
            print(color.yellow("Import cancelled."))
            return

        written = write_imported_maps(result)
        print(color.green("Written:"))
        for path in written:
            print(f"  {path}  (backup: {path}.bak)")
    
    # Menu items — labels only, order = selection index
    YT_MENU = [
        "List playlists",
        "Playlist artists",
        "Tracks out of playlist",
        "Print tracks to file",
        "Update playlist map",
        "Distribute tracks",
        "Download all playlists",
        "Download track",
    ]
    YA_MENU = [
        "Transfer to YouTube Music",
        "Download playlists",
        "Download liked tracks",
        "Get playlist map",
        "Remove broken liked tracks",
        "Sync playlists from YAML",
    ]
    BUILDIN_MENU = [
        "Log in",
        "Status",
        "List MCP tools",
        "Call MCP tool",
        "Log out",
        "Export maps",
        "Import maps",
    ]

    def run(self):
        """Main CLI loop"""
        print(color.cyan_bold("  Music Library CLI"))

        while self.running:
            try:
                # Mode selection
                if self.mode is None:
                    idx = self._select("Select API Mode",
                                       ["YouTube Music", "Yandex Music", "Buildin AI"],
                                       back_label="Exit")
                    if idx == -1:
                        print("\n" + color.cyan("Goodbye!"))
                        self.running = False
                        break
                    self.mode = ['ytmusic', 'yamusic', 'buildin'][idx]

                # YouTube Music mode
                elif self.mode == 'ytmusic':
                    idx = self._select("YouTube Music", self.YT_MENU, back_label="Back")
                    if idx == -1:
                        self.mode = None
                        continue
                    self._dispatch_yt(idx)

                # Yandex Music mode
                elif self.mode == 'yamusic':
                    idx = self._select("Yandex Music", self.YA_MENU, back_label="Back")
                    if idx == -1:
                        self.mode = None
                        continue
                    self._dispatch_ya(idx)

                # Buildin AI mode
                elif self.mode == 'buildin':
                    idx = self._select("Buildin AI", self.BUILDIN_MENU, back_label="Back")
                    if idx == -1:
                        self.mode = None
                        continue
                    self._dispatch_buildin(idx)

            except KeyboardInterrupt:
                print("\n\n" + color.cyan("Goodbye!"))
                self.running = False
            except Exception as e:
                print(color.red(f"\nError: {e}\n"))

    @staticmethod
    def _pause() -> None:
        """Wait for Enter / space / any key before returning to the menu."""
        print()
        input(color.yellow("Press Enter to continue..."))

    def _dispatch_yt(self, idx: int):
        cmds = [
            self.list_playlists,
            self.get_playlist_artists,
            lambda: print(f"Found {len(self.ytmusic.get_track_out_playlist())} tracks"),
            lambda: self.ytmusic.print_tracks(self.ytmusic.get_track_out_playlist()),
            self.ytmusic.update_playlists_map,
            self.ytmusic.distribute_tracks,
            self.ytmusic.download_all_playlists,
            lambda: self.ytmusic.download_track("9zhK-QaEYZY"),
        ]
        cmds[idx]()
        self._pause()

    def _dispatch_ya(self, idx: int):
        cmds = [
            self.transfer_tracks,
            self.yamusic.download_playlists,
            self.yamusic.download_like_tracks,
            self.yamusic.playlist_map,
            self.yamusic.check_tracks,
            self.yamusic.sync_playlists_from_yaml,
        ]
        cmds[idx]()
        self._pause()

    def _dispatch_buildin(self, idx: int):
        cmds = [
            self.buildin_login,
            self.buildin_status,
            self.buildin_tools,
            self.buildin_call_tool,
            self.buildin_logout,
            self.buildin_export_maps,
            self.buildin_import_maps,
        ]
        cmds[idx]()
        self._pause()