import json
import os
from datetime import datetime

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
        
    def print_mode_selection(self):
        """Display mode selection menu"""
        print("\n" + "="*50)
        print("Select API Mode")
        print("="*50)
        print("1. YouTube Music")
        print("2. Yandex Music")
        print("3. Buildin AI")
        print("q, quit, exit - Exit program")
        print("="*50)
    
    def print_ytmusic_menu(self):
        """Display YouTube Music specific menu"""
        print("\n" + "="*50)
        print("YouTube Music Commands")
        print("="*50)
        print("1. List playlists")
        print("2. Get playlist artists")
        print("3. Get tracks from liked playlist")
        print("4. Print tracks to file")
        print("5. Update playlist map")
        print("6. Distribute tracks by playlists")
        print("7. Download all user playlists")
        print("8. Download track")
        print("b, back - Return to mode selection")
        print("q, quit, exit - Exit program")
        print("="*50)
    
    def print_yamusic_menu(self):
        """Display Yandex Music specific menu"""
        print("\n" + "="*50)
        print("Yandex Music Commands")
        print("="*50)
        print("1. Transfer tracks to YouTube Music")
        print("2. Download playlists")
        print("3. Download liked tracks as playlist")
        print("4. Get playlist map")
        print("5. Playlist changes")
        print("6. Sync playlists from yaml")
        print("b, back - Return to mode selection")
        print("q, quit, exit - Exit program")
        print("="*50)
    
    def print_buildin_menu(self):
        """Display Buildin AI specific menu"""
        print("\n" + "="*50)
        print("Buildin AI Commands")
        print("="*50)
        print("1. Log in (browser OAuth)")
        print("2. Show status")
        print("3. List MCP tools")
        print("4. Call MCP tool")
        print("5. Log out")
        print("6. Export playlist maps to Buildin")
        print("7. Import playlist maps from Buildin")
        print("b, back - Return to mode selection")
        print("q, quit, exit - Exit program")
        print("="*50)
    
    def list_playlists(self):
        """List all playlists"""
        try:
            playlists = self.ytmusic.get_playlists()
            self.ytmusic.print_playlists(playlists)
        except Exception as e:
            print(f"Error listing playlists: {e}")
    
    def get_playlist_artists(self):
        """Get artists from a specific playlist"""
        try:
            playlists = self.ytmusic.get_playlists()
            playlist = self.ytmusic.get_playlist(playlists[1]["playlistId"])
            artists = self.ytmusic.get_playlist_artists(playlist)
            print(playlist["title"])
            for artist in artists:
                print(artist)
        except Exception as e:
            print(f"Error getting playlist artists: {e}")

    def move_tracks(self, out_path: str) -> None:
        data = {
            'liked_tracks': [],
            'not_found': [],
            'errors': [],
        }
        
        print('Exporting liked tracks from Yandex Music...')
        tracks = self.yamusic.export_liked_tracks()
        tracks.reverse()

        for track in tracks:
            data['liked_tracks'].append({
                'artist': track.artist,
                'name': track.name
            })

        print('Importing liked tracks to Youtube Music...')
        not_found, errors = self.ytmusic.import_liked_tracks(tracks)

        for track in not_found:
            data['not_found'].append({
                'artist': track.artist,
                'name': track.name
            })
            print(f'Not found: {track.artist} - {track.name}')
        
        for track in errors:
            data['errors'].append({
                'artist': track.artist,
                'name': track.name
            })
            print(f'Error: {track.artist} - {track.name}')
        
        print(f'\nSummary: {len(tracks)} total tracks')
        print(f'Successfully imported: {len(tracks) - len(not_found) - len(errors)}')
        print(f'Not found: {len(not_found)} tracks')
        print(f'Errors: {len(errors)} tracks')

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
    
    def handle_ytmusic_command(self, command):
        """Handle YouTube Music specific commands"""
        if command in ['1', 'list']:
            self.list_playlists()
        elif command in ['2', 'artists']:
            self.get_playlist_artists()
        elif command in ['3', 'tracks']:
            tracks = self.ytmusic.get_track_out_playlist()
            print(f"Found {len(tracks)} tracks in liked playlist")
        elif command in ['4', 'print']:
            tracks = self.ytmusic.get_track_out_playlist()
            self.ytmusic.print_tracks(tracks)
            print(f"Printed {len(tracks)} tracks to logs/tracks.txt")
        elif command in ['5', 'playlist_map']:
            self.ytmusic.update_playlists_map()
        elif command in ['6', 'distribute']:
            self.ytmusic.distribute_tracks()
        elif command in ['7', 'download']:
            self.ytmusic.download_all_playlists()
        elif command in ['8', 'download_track']:
            self.ytmusic.download_track("9zhK-QaEYZY")
        elif command in ['b', 'back']:
            self.mode = None
            print("Returning to mode selection...")
        else:
            print("Unknown command. Type 'help' to see available commands.")
    
    def handle_yamusic_command(self, command):
        """Handle Yandex Music specific commands"""
        if command in ['1', 'transfer']:
            self.transfer_tracks()
        elif command in ['2', 'download_playlists']:
            self.yamusic.download_playlists()
        elif command in ['3', 'download_liked']:
            self.yamusic.download_like_tracks()
        elif command in ['4', 'playlist_map']:
            self.yamusic.playlist_map()
        elif command in ['5', 'p']:
            self.yamusic.check_tracks()
        elif command in ['6', 'sync']:
            self.yamusic.sync_playlists_from_yaml()
        elif command in ['b', 'back']:
            self.mode = None
            print("Returning to mode selection...")
        else:
            print("Unknown command. Type 'help' to see available commands.")
    
    def buildin_ensure_login(self) -> bool:
        """Log in on demand before running a command that needs Buildin auth."""
        if self.buildin.is_authorized():
            return True
        print("Buildin authorization is required for this command.")
        return self.buildin_login()
    
    def buildin_login(self) -> bool:
        try:
            data = self.buildin.login()
        except BuildinError as e:
            print(f"Buildin login failed: {e}")
            return False
        except Exception as e:
            print(f"Buildin login failed: {type(e).__name__}: {e}")
            return False
        
        expires_at = data.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Logged in to Buildin MCP. Access token expires at {expires} (auto-refreshed).")
        else:
            print("Logged in to Buildin MCP.")
        return True
    
    def buildin_status(self):
        status = self.buildin.status()
        print(f"MCP endpoint: {status['mcp_url']}")
        print(f"Token file:   {status['token_file']}")
        if not status["authorized"]:
            print("Status:       not authorized (use command 1 to log in)")
            return
        if os.environ.get("BUILDIN_ACCESS_TOKEN"):
            print("Status:       authorized via BUILDIN_ACCESS_TOKEN")
            return
        expires_at = status.get("expires_at")
        if expires_at:
            expires = datetime.fromtimestamp(float(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Status:       authorized (token expires at {expires})")
        else:
            print("Status:       authorized")
    
    def buildin_tools(self):
        if not self.buildin_ensure_login():
            return
        try:
            tools = self.buildin.list_tools()
        except BuildinError as e:
            print(f"Could not list Buildin tools: {e}")
            return
        
        if not tools:
            print("The Buildin MCP server exposes no tools.")
            return
        
        print(f"{len(tools)} Buildin MCP tools:")
        for tool in tools:
            name = tool.get("name", "?")
            description = " ".join((tool.get("description") or "").split())
            if description:
                print(f"  - {name}: {description[:140]}")
            else:
                print(f"  - {name}")
    
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
            print(f"Buildin tool call failed: {e}")
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
        print("Buildin tokens removed.")
    
    def buildin_export_maps(self):
        if not self.buildin_ensure_login():
            return
        print("Exporting local playlist maps to Buildin...")
        try:
            result = export_maps(self.buildin)
        except MapSyncError as e:
            print(f"Buildin export failed: {e}")
            return
        
        print(f"Page:     {result['page_id']}")
        print(f"Database: {result['database_id']}")
        print(
            f"Records:  {result['created']} created, {result['updated']} updated, "
            f"{result['unchanged']} unchanged (total {result['total']})"
        )
        if result["orphaned"]:
            print("Orphaned in Buildin (no local counterpart; delete manually in the UI):")
            for platform, title in result["orphaned"]:
                print(f"  - {platform}: {title}")
    
    def buildin_import_maps(self):
        if not self.buildin_ensure_login():
            return
        print("Reading playlist maps from Buildin...")
        try:
            result = import_maps(self.buildin)
        except MapSyncError as e:
            print(f"Buildin import failed: {e}")
            return
        
        print(
            f"Records: {result['records']} | YouTube: {len(result['youtube'])} | "
            f"Yandex: {len(result['yandex'])}"
        )
        for platform, key in (("YouTube", "youtube_diff"), ("Yandex", "yandex_diff")):
            diff = result[key]
            print(
                f"{platform} changes vs local: +{len(diff['added'])} "
                f"-{len(diff['removed'])} ~{len(diff['changed'])}"
            )
            for label in ("added", "removed", "changed"):
                values = diff[label]
                for value in values[:10]:
                    print(f"  {label}: {value}")
                if len(values) > 10:
                    print(f"  ... {len(values) - 10} more {label}")
        
        if not result["youtube"]:
            print("No YouTube records in Buildin — data/playlists_map.yaml will be kept.")
        if not result["yandex"]:
            print("No Yandex records in Buildin — data/yamusic.yaml will be kept.")
        if not result["youtube"] and not result["yandex"]:
            return
        
        confirm = input("\nOverwrite local YAML maps with the Buildin data? (y/n): ")
        if confirm.strip().lower() not in ("y", "yes"):
            print("Import cancelled.")
            return
        
        written = write_imported_maps(result)
        print("Written:")
        for path in written:
            print(f"  {path} (backup: {path}.bak)")
    
    def handle_buildin_command(self, command):
        """Handle Buildin AI specific commands"""
        if command in ['1', 'login']:
            self.buildin_login()
        elif command in ['2', 'status']:
            self.buildin_status()
        elif command in ['3', 'tools']:
            self.buildin_tools()
        elif command in ['4', 'call']:
            self.buildin_call_tool()
        elif command in ['5', 'logout']:
            self.buildin_logout()
        elif command in ['6', 'export_maps', 'export-maps']:
            self.buildin_export_maps()
        elif command in ['7', 'import_maps', 'import-maps']:
            self.buildin_import_maps()
        elif command in ['b', 'back']:
            self.mode = None
            print("Returning to mode selection...")
        else:
            print("Unknown command. Type 'help' to see available commands.")
    
    def run(self):
        """Main CLI loop"""
        print("\n" + "="*50)
        print("YouTube Music / Yandex Music / Buildin AI CLI")
        print("="*50)
        
        while self.running:
            try:
                # Mode selection
                if self.mode is None:
                    self.print_mode_selection()
                    mode_input = input("\nSelect mode (1/2/3): ").strip().lower()
                    
                    if mode_input in ['q', 'quit', 'exit']:
                        print("Goodbye!")
                        self.running = False
                        break
                    elif mode_input in ['1', 'yt', 'ytmusic']:
                        self.mode = 'ytmusic'
                        print("\nSwitched to YouTube Music mode")
                        self.print_ytmusic_menu()
                    elif mode_input in ['2', 'ya', 'yamusic']:
                        self.mode = 'yamusic'
                        print("\nSwitched to Yandex Music mode")
                        self.print_yamusic_menu()
                    elif mode_input in ['3', 'buildin', 'ai']:
                        self.mode = 'buildin'
                        print("\nSwitched to Buildin AI mode")
                        self.print_buildin_menu()
                    else:
                        print("Invalid mode selection. Please choose 1, 2 or 3.")
                
                # YouTube Music mode
                elif self.mode == 'ytmusic':
                    command = input("\n[YTMusic] Enter command (or 'help' for menu): ").strip().lower()
                    
                    if command in ['q', 'quit', 'exit']:
                        print("Goodbye!")
                        self.running = False
                    elif command in ['help', '?', '']:
                        self.print_ytmusic_menu()
                    else:
                        self.handle_ytmusic_command(command)
                
                # Yandex Music mode
                elif self.mode == 'yamusic':
                    command = input("\n[YaMusic] Enter command (or 'help' for menu): ").strip().lower()
                    
                    if command in ['q', 'quit', 'exit']:
                        print("Goodbye!")
                        self.running = False
                    elif command in ['help', '?', '']:
                        self.print_yamusic_menu()
                    else:
                        self.handle_yamusic_command(command)
                
                # Buildin AI mode
                elif self.mode == 'buildin':
                    command = input("\n[Buildin] Enter command (or 'help' for menu): ").strip().lower()
                    
                    if command in ['q', 'quit', 'exit']:
                        print("Goodbye!")
                        self.running = False
                    elif command in ['help', '?', '']:
                        self.print_buildin_menu()
                    else:
                        self.handle_buildin_command(command)
            
            except KeyboardInterrupt:
                print("\n\nGoodbye!")
                self.running = False
            except Exception as e:
                print(f"Error: {e}")