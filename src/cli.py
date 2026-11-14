import json
import os
from datetime import datetime
from typing import Optional

from . import color, paths
from .yamusic import YaMusicHandle
from .ytmusic import YTMusicClient
from .buildin import BuildinClient, BuildinError
from .buildin_maps import MapSyncError, export_maps, import_maps, write_imported_maps
from .telegram import TelegramClient, TelegramError
from .telegram_user import TelegramUserClient
from .telegram_commands import create_handler
from .yandex_disk import YandexDiskClient, YandexDiskError


class CLI:
    # Menu items — labels only, order = selection index
    YT_MENU = [
        "List playlists",
        "Playlist artists",
        "Tracks out of playlist",
        "Print tracks to file",
        "Update playlist map",
        "Distribute tracks",
        "Download all playlists",
        "Download track (demo)",
    ]
    YA_MENU = [
        "Transfer to YouTube Music",
        "Download playlists",
        "Download liked tracks",
        "Get playlist map",
        "Remove broken liked tracks (destructive)",
        "Sync playlists from YAML (destructive)",
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
    TELEGRAM_MENU = [
        "Status",
        "Send test message",
        "Broadcast message",
        "Allow users (whitelist)",
        "Start command listener",
        "User: status (account session)",
        "User: log in (code or QR)",
        "User: Saved Messages",
        "User: log out",
    ]
    YANDEX_DISK_MENU = [
        "Log in (paste token)",
        "Status",
        "List directory",
        "Download file",
        "Upload file",
        "Delete file/folder (destructive)",
        "Log out",
    ]

    def __init__(self, yamusic: YaMusicHandle, ytmusic: YTMusicClient,
                 buildin: BuildinClient, args,
                 telegram: Optional[TelegramClient] = None,
                 telegram_user: Optional[TelegramUserClient] = None,
                 yandex_disk: Optional[YandexDiskClient] = None) -> None:
        self.yamusic = yamusic
        self.ytmusic = ytmusic
        self.buildin = buildin
        self.args = args
        self.telegram = telegram
        self.telegram_user = telegram_user
        self.yandex_disk = yandex_disk
        self.running = True
        self.mode: Optional[str] = None  # 'ytmusic', 'yamusic', 'buildin', 'telegram' or 'yandex_disk'

    @staticmethod
    def _select(title: str, items: list[str],
               back_label: str = "Back") -> int:
        """Interactive curses menu. Returns 0-based index, or -1 for back/quit."""
        import curses  # lazy: curses is only needed when the menu actually runs

        footer = [f"{back_label}  ·  q / esc to {back_label.lower()}",
                  "↑/↓ move  ·  enter select  ·  1-N quick pick"]

        def _run(stdscr) -> int:
            curses.curs_set(0)
            stdscr.keypad(True)
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
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
                # Mouse events are multi-byte: consume the rest of the packet so
                # its bytes (which begin with an ESC) are not mistaken for "esc".
                if key == curses.KEY_MOUSE:
                    mx, my, _, _, _ = curses.getmouse()
                    if 2 + selected[0] == my:  # row of the highlighted item
                        selected[0] = my - 2
                    elif 2 <= my < 2 + n:  # click another item
                        selected[0] = my - 2
                    frame()
                    continue
                if key in (ord('q'), ord('Q')) or key == 27:
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
            return selected[0]

        return curses.wrapper(_run)
    
    def list_playlists(self) -> None:
        """List all playlists"""
        try:
            playlists = self.ytmusic.get_playlists()
            for p in playlists:
                print(f"  {color.cyan(p['title'])}: {p['playlistId']}")
        except Exception as e:
            print(color.red(f"Error listing playlists: {e}"))
    
    def get_playlist_artists(self) -> None:
        """Get artists from a specific playlist"""
        if len(playlists := self.ytmusic.get_playlists()) < 2:
            print(color.red("Need at least 2 playlists to pick from."))
            return
        try:
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

        self._notify_telegram(
            f"🎵 Yandex → YouTube transfer: {len(tracks) - len(not_found) - len(errors)} "
            f"imported / {len(not_found)} not found / {len(errors)} errors (of {len(tracks)})"
        )

        str_data = json.dumps(data, indent=2, ensure_ascii=False)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(str_data)
    
    def transfer_tracks(self) -> None:
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
    
    def buildin_status(self) -> None:
        status = self.buildin.status()
        print(f"  MCP endpoint: {color.cyan(status['mcp_url'])}")
        print(f"  Config file:  {status['config_file']}")
        print(f"  Credentials:  {color.cyan('buildin.auth')} (written by the app)")
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
    
    def buildin_tools(self) -> None:
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
    
    def buildin_call_tool(self) -> None:
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
    
    def print_tool_result(self, result: dict) -> None:
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
    
    def buildin_logout(self) -> None:
        self.buildin.logout()
        print(color.green("Buildin tokens removed."))
    
    def buildin_export_maps(self) -> None:
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
    
    def buildin_import_maps(self) -> None:
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

    # ------------------------------------------------------------------ Telegram
    def _notify_telegram(self, text: str) -> None:
        """Best-effort broadcast to Telegram after a CLI operation. Silent if
        Telegram is unconfigured or the send fails — never interrupts the CLI."""
        if self.telegram is None or not self.telegram.token:
            return
        try:
            self.telegram.broadcast(text)
        except Exception as e:
            print(color.yellow(f"(Telegram notification failed: {e})"))

    def _download(self, fn, message: str, *args):
        """Run a download callable, then broadcast a Telegram completion message."""
        fn(*args)
        self._notify_telegram(message)

    def _need_telegram(self) -> Optional[TelegramClient]:
        """Return the Telegram client, or None with a message if unconfigured."""
        if self.telegram is None:
            print(color.red("Telegram is not configured (no telegram.token in config/config.yaml)."))
            return None
        return self.telegram

    def telegram_status(self) -> None:
        tg = self._need_telegram()
        if tg is None:
            return
        try:
            info = tg.status()
        except TelegramError as e:
            print(color.red(f"Telegram status failed: {e}"))
            return
        if not info["configured"]:
            print(color.red("Not configured (missing token)."))
            return
        print(f"  Bot:        {color.cyan('@' + (info.get('bot_username') or 'unknown'))}")
        if info.get("transport") == "mtproto":
            print(f"  Transport:  {color.cyan('MTProto')} via {info['endpoint']}")
        else:
            print(f"  API base:   {info['api_base']}")
            print(f"  Proxy:      {color.green('on') if info['proxy'] else color.red('off')}")
        print(f"  Chats:      {info['chats'] or color.yellow('(none — run Start listener to auto-capture)')}")
        allowed = info["allow"] if info["allow"] else "anyone (open)"
        print(f"  Allowed:    {allowed}")
        if info.get("error"):
            print(color.yellow(f"  Note: {info['error']}"))
            if info.get("transport") == "mtproto":
                print(color.yellow("  → MTProto connect failed. Check telegram.api_id / api_hash (my.telegram.org)"))
                print(color.yellow("    and telegram.mtproto (host/port/secret, proxy running)."))
            else:
                print(color.yellow("  → Can't reach api.telegram.org. If this network blocks Telegram,"))
                print(color.yellow("    configure telegram.mtproto or run the listener on a machine that can reach it."))

    def telegram_test(self) -> None:
        tg = self._need_telegram()
        if tg is None:
            return
        if not tg.chats:
            print(color.yellow("No chats known. Run 'Start command listener' first (auto-capture), or add chats to config/telegram.json."))
            return
        try:
            sent = tg.broadcast("🎵 Music bot: test message")
        except TelegramError as e:
            print(color.red(f"Send failed: {e}"))
            return
        print(color.green(f"Test message sent to {sent} chat(s)."))

    def telegram_broadcast(self) -> None:
        tg = self._need_telegram()
        if tg is None:
            return
        if not tg.chats:
            print(color.yellow("No chats known — nothing to broadcast to."))
            return
        text = input("Message to broadcast: ").strip()
        if not text:
            print("No message given.")
            return
        try:
            sent = tg.broadcast(text)
        except TelegramError as e:
            print(color.red(f"Broadcast failed: {e}"))
            return
        print(color.green(f"Sent to {sent} chat(s)."))

    def telegram_allow(self) -> None:
        tg = self._need_telegram()
        if tg is None:
            return
        current = ", ".join(map(str, tg.allow)) if tg.allow else "(open — anyone)"
        print(f"  Currently allowed: {current}")
        raw = input("Allowed user ids, comma-separated (empty = open): ").strip()
        try:
            ids = [int(x) for x in raw.replace(" ", "").split(",") if x] if raw else []
        except ValueError:
            print(color.red("Invalid ids — use numbers only, comma-separated."))
            return
        tg.set_allow(ids)
        print(color.green("Allow-list saved."))

    def telegram_listen(self) -> None:
        tg = self._need_telegram()
        if tg is None:
            return
        print(color.cyan("Starting Telegram command listener (Ctrl+C to stop)…"))
        print(color.yellow("Commands run here block until each finishes; long downloads take a while."))
        handler = create_handler(self.yamusic, self.ytmusic, self.buildin, tg)
        try:
            tg.run_commands(handler)
        except TelegramError as e:
            print(color.red(f"Listener stopped: {e}"))
        except KeyboardInterrupt:
            print(color.cyan("\nListener stopped."))

    # ------------------------------------------------- Telegram user account
    def _need_telegram_user(self) -> Optional[TelegramUserClient]:
        """Return the user-account client, or None with a message if unusable."""
        if self.telegram_user is None:
            print(color.red("Telegram user session is not configured (no telegram.api_id/api_hash)."))
            return None
        if not self.telegram_user.configured:
            print(color.red("Telegram user session needs telegram.api_id and telegram.api_hash (my.telegram.org)."))
            return None
        return self.telegram_user

    def telegram_user_status(self) -> None:
        tu = self._need_telegram_user()
        if tu is None:
            return
        try:
            info = tu.status()
        except TelegramError as e:
            print(color.red(f"User session status failed: {e}"))
            return
        print(f"  Session:    {info['session']}")
        phone = info["phone"] or color.yellow("(not set — you will be asked at login)")
        print(f"  Phone:      {phone}")
        if info["authorized"]:
            who = info.get("name") or "unknown"
            if info.get("username"):
                who += f" (@{info['username']})"
            print(f"  Account:    {color.cyan(who)}  id {info.get('id')}")
        else:
            print(f"  Account:    {color.yellow('not logged in — run User: log in')}")
        if info.get("error"):
            print(color.yellow(f"  Note: {info['error']}"))

    def telegram_user_login(self) -> None:
        tu = self._need_telegram_user()
        if tu is None:
            return
        print("  Login method:")
        print("    1) QR code — scan with your phone (recommended, no code)")
        print("    2) login code sent by Telegram (app/SMS)")
        print("    3) SMS code (forced)")
        choice = input("Choose [1/2/3] (default 1): ").strip() or "1"
        try:
            if choice == "2":
                me = tu.login()
            elif choice == "3":
                me = tu.login(force_sms=True)
            else:
                me = tu.login_qr()
        except TelegramError as e:
            print(color.red(f"Login failed: {e}"))
            return
        except KeyboardInterrupt:
            print(color.cyan("\nLogin cancelled."))
            return
        who = me.get("name") or "unknown"
        if me.get("username"):
            who += f" (@{me['username']})"
        print(color.green(f"Logged in as {who} (id {me.get('id')})."))

    def telegram_saved(self) -> None:
        """Print the newest messages from the account's Saved Messages."""
        tu = self._need_telegram_user()
        if tu is None:
            return
        raw = input("How many messages (default 20): ").strip()
        limit = int(raw) if raw.isdigit() and int(raw) > 0 else 20
        try:
            messages = tu.get_saved_messages(limit=limit)
        except TelegramError as e:
            print(color.red(f"Could not read Saved Messages: {e}"))
            return
        if not messages:
            print(color.yellow("Saved Messages is empty."))
            return
        print(color.cyan(f"  Saved Messages — {len(messages)} message(s), newest first:"))
        for m in messages:
            text = " ".join((m["text"] or "").split())
            if len(text) > 200:
                text = text[:197] + "…"
            media = f" [{m['media']}]" if m["media"] else ""
            print(f"  #{m['id']}  {m['date']}{media}")
            print(f"    {text or '(no text)'}")

    def telegram_user_logout(self) -> None:
        tu = self._need_telegram_user()
        if tu is None:
            return
        if input("Log out the Telegram user session? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return
        tu.logout()
        print(color.green("User session logged out and session file removed."))

    def run(self) -> None:
        """Main CLI loop"""
        print(color.cyan_bold("  Music Library CLI"))

        while self.running:
            try:
                # Mode selection
                if self.mode is None:
                    idx = self._select("Select API Mode",
                                       ["YouTube Music", "Yandex Music", "Buildin AI", "Telegram", "Yandex Disk"],
                                       back_label="Exit")
                    if idx == -1:
                        print("\n" + color.cyan("Goodbye!"))
                        self.running = False
                        break
                    self.mode = ['ytmusic', 'yamusic', 'buildin', 'telegram', 'yandex_disk'][idx]

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

                # Telegram mode
                elif self.mode == 'telegram':
                    idx = self._select("Telegram", self.TELEGRAM_MENU, back_label="Back")
                    if idx == -1:
                        self.mode = None
                        continue
                    self._dispatch_telegram(idx)

                # Yandex Disk mode
                elif self.mode == 'yandex_disk':
                    idx = self._select("Yandex Disk", self.YANDEX_DISK_MENU, back_label="Back")
                    if idx == -1:
                        self.mode = None
                        continue
                    self._dispatch_yandex_disk(idx)

            except KeyboardInterrupt:
                print("\n\n" + color.cyan("Goodbye!"))
                self.running = False
            except Exception as e:
                print(color.red(f"\nError: {e}"))

    @staticmethod
    def _pause() -> None:
        """Wait for Enter / space / any key before returning to the menu."""
        print()
        input(color.yellow("Press Enter to continue..."))

    def _dispatch_yt(self, idx: int) -> None:
        assert 0 <= idx < len(self.YT_MENU), f"Invalid YT menu index: {idx}"
        cmds = [
            self.list_playlists,
            self.get_playlist_artists,
            lambda: print(f"Found {len(self.ytmusic.get_track_out_playlist())} tracks"),
            lambda: self.ytmusic.print_tracks(self.ytmusic.get_track_out_playlist()),
            self.ytmusic.update_playlists_map,
            self.ytmusic.distribute_tracks,
            lambda: self._download(self.ytmusic.download_all_playlists,
                                   "⬇️ YouTube Music: downloaded all playlists"),
            lambda: self._download(self.ytmusic.download_track, "9zhK-QaEYZY"),
        ]
        cmds[idx]()
        self._pause()

    def _dispatch_ya(self, idx: int) -> None:
        assert 0 <= idx < len(self.YA_MENU), f"Invalid YA menu index: {idx}"
        cmds = [
            self.transfer_tracks,
            lambda: self._download(self.yamusic.download_playlists,
                                   "⬇️ Yandex Music: downloaded all playlists"),
            lambda: self._download(self.yamusic.download_like_tracks,
                                   "⬇️ Yandex Music: downloaded liked tracks"),
            self.yamusic.playlist_map,
            self.yamusic.check_tracks,
            self.yamusic.sync_playlists_from_yaml,
        ]
        cmds[idx]()
        self._pause()

    def _dispatch_buildin(self, idx: int) -> None:
        assert 0 <= idx < len(self.BUILDIN_MENU), f"Invalid Buildin menu index: {idx}"
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

    def _dispatch_telegram(self, idx: int) -> None:
        assert 0 <= idx < len(self.TELEGRAM_MENU), f"Invalid Telegram menu index: {idx}"
        cmds = [
            self.telegram_status,
            self.telegram_test,
            self.telegram_broadcast,
            self.telegram_allow,
            self.telegram_listen,
            self.telegram_user_status,
            self.telegram_user_login,
            self.telegram_saved,
            self.telegram_user_logout,
        ]
        cmds[idx]()
        self._pause()

    # ---------------------------------------------------------- Yandex Disk
    def _need_yandex_disk(self) -> Optional[YandexDiskClient]:
        """Return the Yandex Disk client, or None with a message if unusable."""
        if self.yandex_disk is None:
            print(color.red("Yandex Disk is not available."))
            return None
        return self.yandex_disk

    def _yandex_disk_ensure_login(self) -> bool:
        """Log in on demand before running a command that needs Disk auth."""
        disk = self._need_yandex_disk()
        if disk is None:
            return False
        if disk.is_authorized():
            return True
        print(color.yellow("Yandex Disk authorization is required for this command."))
        return self.yandex_disk_login()

    def yandex_disk_login(self) -> bool:
        disk = self._need_yandex_disk()
        if disk is None:
            return False
        try:
            data = disk.login()
        except YandexDiskError as e:
            print(color.red(f"Yandex Disk login failed: {e}"))
            return False
        except KeyboardInterrupt:
            print(color.cyan("\nYandex Disk login cancelled."))
            return False
        except Exception as e:
            print(color.red(f"Yandex Disk login failed: {type(e).__name__}: {e}"))
            return False

        expires_at = data.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(color.green(f"Logged in to Yandex Disk. Token expires at {expires} (auto-refreshed)."))
        else:
            print(color.green("Logged in to Yandex Disk."))
        return True

    def yandex_disk_status(self) -> None:
        disk = self._need_yandex_disk()
        if disk is None:
            return
        status = disk.status()
        print(f"  API base:    {color.cyan(status['api_base'])}")
        print(f"  Config file: {status['config_file']}")
        print(f"  Credentials: {color.cyan('yandex_disk.auth')} (written by the app)")
        print(f"  Scope:       {status['scope']}")
        if not status["authorized"]:
            print(f"  Status:      {color.red('not authorized')} (run Log in first)")
            return
        if status["env_override"]:
            print(f"  Status:      {color.green('authorized')} via YANDEX_DISK_TOKEN")
            return
        expires_at = status.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"  Status:      {color.green('authorized')} (token expires at {expires})")
        else:
            print(f"  Status:      {color.green('authorized')}")

    def yandex_disk_list(self) -> None:
        if not self._yandex_disk_ensure_login():
            return
        disk = self.yandex_disk
        path = input("Disk path to list (default /): ").strip() or "/"
        try:
            items = disk.list_dir(path)
        except YandexDiskError as e:
            print(color.red(f"Could not list {path}: {e}"))
            return
        if not items:
            print(color.yellow(f"{path} is empty."))
            return
        print(color.cyan(f"  {len(items)} item(s) in {path}:"))
        for item in items:
            name = item.get("name", "?")
            size = item.get("size")
            kind = item.get("type", "?")
            extra = f"  ({size:,} bytes)" if kind == "file" and size is not None else ""
            prefix = "▸ " if kind == "dir" else "  "
            print(f"  {prefix}{color.cyan(name)}{extra}")

    def yandex_disk_download(self) -> None:
        if not self._yandex_disk_ensure_login():
            return
        disk = self.yandex_disk
        path = input("Disk file path to download: ").strip()
        if not path:
            print("No path given.")
            return
        raw_dest = input("Local destination (dir or file; empty = default downloads/yandex_disk): ").strip()
        dest = paths.resolve(raw_dest) if raw_dest else None
        try:
            result = disk.download(path, dest)
        except YandexDiskError as e:
            print(color.red(f"Download failed: {e}"))
            return
        if result:
            print(color.green(f"Saved to {result}"))
        else:
            print(color.yellow("Download failed (see the log for details)."))

    def yandex_disk_upload(self) -> None:
        if not self._yandex_disk_ensure_login():
            return
        disk = self.yandex_disk
        local = paths.resolve(input("Local file to upload: ").strip())
        if not local.is_file():
            print(color.red(f"Not a file: {local}"))
            return
        target = input("Disk target path (e.g. /music/artist - title.mp3): ").strip()
        if not target:
            print("No target path given.")
            return
        overwrite = input("Overwrite if it already exists? [y/N] ").strip().lower() in ("y", "yes")
        try:
            committed = disk.upload(local, target, overwrite=overwrite)
        except YandexDiskError as e:
            print(color.red(f"Upload failed: {e}"))
            return
        if committed:
            print(color.green(f"Uploaded {local} -> {target}"))
        else:
            print(color.yellow("Upload not completed (skipped or failed — see the log)."))

    def yandex_disk_delete(self) -> None:
        if not self._yandex_disk_ensure_login():
            return
        disk = self.yandex_disk
        path = input("Disk path to DELETE (file or folder): ").strip()
        if not path:
            print("No path given.")
            return
        if input(f"Really delete {path}? This cannot be undone. [y/N] ").strip().lower() not in ("y", "yes"):
            print(color.yellow("Deleted nothing — cancelled."))
            return
        try:
            ok = disk.delete(path)
        except YandexDiskError as e:
            print(color.red(f"Delete failed: {e}"))
            return
        if ok:
            print(color.green(f"Deleted {path}"))
        else:
            print(color.yellow("Delete did not succeed."))

    def yandex_disk_logout(self) -> None:
        disk = self._need_yandex_disk()
        if disk is None:
            return
        if input("Log out of Yandex Disk (remove stored tokens)? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return
        disk.logout()
        print(color.green("Yandex Disk tokens removed."))

    def _dispatch_yandex_disk(self, idx: int) -> None:
        assert 0 <= idx < len(self.YANDEX_DISK_MENU), f"Invalid Yandex Disk menu index: {idx}"
        cmds = [
            self.yandex_disk_login,
            self.yandex_disk_status,
            self.yandex_disk_list,
            self.yandex_disk_download,
            self.yandex_disk_upload,
            self.yandex_disk_delete,
            self.yandex_disk_logout,
        ]
        cmds[idx]()
        self._pause()