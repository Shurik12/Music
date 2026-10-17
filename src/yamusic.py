import os
import yaml
from yandex_music import Client, Artist, Playlist
from yandex_music.utils.difference import Difference
from typing import List, Set

from .track import Track
from . import paths
from tqdm import tqdm


class YaMusicHandle:
    def __init__(self, token: str):
        self.client = Client(token).init()

    def export_liked_tracks(self) -> List[Track]:
        tracks = self.client.users_likes_tracks().tracks

        result = []
        skipped_count = 0
        
        with tqdm(total=len(tracks), position=0, desc='Export tracks') as pbar:
            with tqdm(total=0, bar_format='{desc}', position=1) as trank_log:
                for i, track_short in enumerate(tracks):
                    try:
                        track = track_short.fetch_track()
                        
                        # Safely handle the case where there are no artists
                        if track.artists_name():
                            artist = track.artists_name()[0]
                        else:
                            artist = "Unknown Artist"
                        name = track.title
                        
                        result.append(Track(artist, name))
                        pbar.update(1)
                        trank_log.set_description_str(f'{i+1}/{len(tracks)}: {artist} - {name}')
                        
                    except TypeError as e:
                        # Skip tracks with the "missing id" error
                        if "missing 1 required positional argument: 'id'" in str(e):
                            skipped_count += 1
                            pbar.update(1)
                            pbar.write(f"Skipped track {i+1}: Missing artist ID")
                        else:
                            # Re-raise other TypeErrors
                            raise e
                            
                    except Exception as e:
                        # Skip tracks with any other errors
                        skipped_count += 1
                        pbar.update(1)
                        pbar.write(f"Skipped track {i+1}: {type(e).__name__}: {str(e)[:50]}...")
        
        print(f"\nSuccessfully exported {len(result)} tracks")
        if skipped_count > 0:
            print(f"Skipped {skipped_count} tracks due to errors")
        
        return result

    def get_playlists(self) -> List[Playlist]:
        try:
            playlists = self.client.users_playlists_list()
            return playlists
        except Exception as e:
            print(f"Error getting library playlists: {e}")
            return []
        
    def get_playlist_artists(self, playlist: Playlist) -> Set[str]:
        artists = set()
        try:
            tracks = playlist.fetch_tracks()
            for track in tracks:
                for artist in track.track.artists:
                    artists.add(artist.name)
        except:
            artists = set()
        return artists
        
    def print_playlists(self):
        playlists = self.client.users_playlists_list()
        for playlist in playlists:
            print (f"{playlist.title}: {playlist.kind}")

    def playlist_map(self, output_file: str | None = None):
        output_file = output_file or str(paths.DATA_DIR / "temp_playlist_map.yaml")
        print("Fetching playlists...")
        playlists = self.client.users_playlists_list()
        
        if not playlists:
            print("No playlists found.")
            return
        
        print(f"Found {len(playlists)} playlists")
        
        playlists_map = {}
        
        for playlist in tqdm(playlists, desc="Processing playlists"):
            
            artists = self.get_playlist_artists(playlist)
            key = playlist["title"].replace(":", " -")  # Avoid YAML key issues with colons
            
            playlists_map[key] = {
                "kind": playlist["kind"],
                "artists": sorted(list(artists))
            }
        
        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(playlists_map, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"\nCurrent playlists map saved to {output_file}")
        print(f"Total playlists in map: {len(playlists_map)}")

    def create_playlist(self):
        playlist = self.client.users_playlists_create("Test")
        print(f'{playlist.title}: {playlist.kind}')
        return playlist.kind

    def add_tracks_to_playlist(self, kind):
        playlist = self.client.users_playlists(kind)
        like_tracks = self.client.users_likes_tracks().tracks[15:25]
        tracks = []
        for track in like_tracks:
            track_data = {
                'id': str(track['id']),
                'album_id': str(track['album_id'])
            }
            tracks.append(track_data)
        diff = Difference()
        diff.add_insert(0, tracks)
        self.client.users_playlists_change(playlist.kind, diff.to_json(), playlist.revision)

    def delete_tracks_from_playlist(self, kind):
        playlist = self.client.users_playlists(kind)
        diff = Difference()
        diff.add_delete(0, playlist.track_count)
        self.client.users_playlists_change(playlist.kind, diff.to_json(), playlist.revision)

    def delete_playlist(self, kind):
        self.client.users_playlists_delete(kind)


    def download_tracks(self, tracks, name):
        chars_to_remove = ['/', '"', ':', "?", "*", "¿"]
        folder = paths.DOWNLOAD_DIR / name
        os.makedirs(folder, exist_ok=True)
        existed_tracks = [f"{folder}/{f}" for f in os.listdir(folder)]
        for track in tqdm(tracks, desc="Downloading tracks"):
            try:
                title = track["title"]
                for char in chars_to_remove:
                    title = title.replace(char, "")

                if track["artists"] and len(track["artists"]) > 0:
                    artist = track["artists"][0]["name"]
                    for char in chars_to_remove:
                        artist = artist.replace(char, "")
                    filename = f"{folder}/{artist} - {title}.mp3"
                else:
                    filename = f"{folder}/{title}.mp3"
                if filename not in existed_tracks: 
                    download_infos = track.get_download_info()
                    bitrate = 192
                    for download_info in download_infos:
                        bitrate = max(download_info["bitrate_in_kbps"], bitrate)
                    track.download(filename, 'mp3', bitrate)
            except Exception as e:
                print(f"  Skipping track: {e}")
                continue
                

    def download_playist(self, playlist: Playlist):
        short_tracks = playlist.fetch_tracks()
        print(f"Get {len(short_tracks)} tracks from playlist {playlist["title"]}")
        track_ids = [track["id"] for track in short_tracks]
        tracks = self.client.tracks(track_ids)
        self.download_tracks(tracks, playlist["title"])

    def download_playlists(self):
        playlists = self.get_playlists()
        for playlist in playlists:
            self.download_playist(playlist)

    def download_like_tracks(self):
        trackslist = self.client.users_likes_tracks()
        if trackslist:
            tracks = trackslist.fetch_tracks()
            self.download_tracks(tracks, "Like")


    def sync_playlists_from_yaml(self, yaml_file: str = str(paths.YAMUSIC_MAP_FILE)):
        """
        Read playlist configuration from YAML file, clear existing playlists,
        and populate them with liked tracks based on artist matching.
        
        Args:
            yaml_file: Path to the YAML configuration file
        """
        # Read YAML file
        print(f"Reading playlist configuration from {yaml_file}")
        with open(yaml_file, 'r', encoding='utf-8') as f:
            playlists_config = yaml.safe_load(f)
        
        # Get all user playlists
        print("Fetching existing playlists...")
        existing_playlists = {p.title: p for p in self.client.users_playlists_list()}
        
        # Get all liked tracks
        print("Fetching liked tracks...")
        trackslist = self.client.users_likes_tracks()
        liked_tracks = trackslist.fetch_tracks()

        print(f"Found {len(liked_tracks)} liked tracks")
        
        # Process each playlist from YAML
        for playlist_name, config in tqdm(playlists_config.items(), desc="Processing playlists"):
            kind = config.get('kind')
            artists = set(config.get('artists', []))
            
            # Check if playlist exists and create if needed
            if not kind or playlist_name not in existing_playlists:
                print(f"\nPlaylist '{playlist_name}' not found or missing kind, creating...")
                try:
                    # Create new playlist
                    new_playlist = self.client.users_playlists_create(playlist_name)
                    kind = new_playlist.kind
                    print(f"  Created playlist with kind: {kind}")
                    
                    # Update the config in memory (optional, doesn't save to file)
                    config['kind'] = kind
                    
                    # Refresh existing playlists dictionary
                    existing_playlists = {p.title: p for p in self.client.users_playlists_list()}
                except Exception as e:
                    print(f"  Failed to create playlist '{playlist_name}': {e}")
                    continue
            
            # Get the playlist to ensure we have valid kind
            if playlist_name in existing_playlists:
                playlist = existing_playlists[playlist_name]
                kind = playlist.kind
            else:
                print(f"\nWarning: Playlist '{playlist_name}' still not found after creation attempt, skipping")
                continue
            
            print(f"\nProcessing playlist: {playlist_name} (kind: {kind})")
            
            # Clear the playlist
            print(f"  Clearing playlist...")
            try:
                self.delete_tracks_from_playlist(kind)
            except Exception as e:
                print(f"  Warning: Could not clear playlist: {e}")
            
            # Find tracks by artists from this playlist
            tracks_to_add = []
            for track in tqdm(liked_tracks, desc=f"  Finding tracks for {playlist_name}", leave=False):
                track_artists = set()
                for artist in track.artists:
                    track_artists.add(artist.name)
                
                # Check if any artist from this track matches the playlist's artists
                if track_artists & artists:  # Intersection of sets
                    # Get album_id safely
                    album_id = None
                    if track.albums and len(track.albums) > 0:
                        album_id = str(track.albums[0].id)
                    
                    tracks_to_add.append({
                        'id': str(track.id),
                        'album_id': album_id
                    })
            
            # Add tracks to playlist if any found
            if tracks_to_add:
                print(f"  Found {len(tracks_to_add)} tracks to add")
                
                # Yandex Music API has limits on how many tracks can be added at once
                # Adding in batches of 50
                batch_size = 50
                total_added = 0
                
                for i in range(0, len(tracks_to_add), batch_size):
                    batch = tracks_to_add[i:i+batch_size]
                    
                    try:
                        # Get current playlist to get latest revision
                        playlist = self.client.users_playlists(kind)
                        
                        # Create difference and add tracks
                        diff = Difference()
                        diff.add_insert(playlist.track_count, batch)
                        
                        # Apply changes
                        self.client.users_playlists_change(kind, diff.to_json(), playlist.revision)
                        total_added += len(batch)
                        print(f"    Added batch of {len(batch)} tracks (total: {total_added})")
                        
                    except Exception as e:
                        print(f"    Error adding batch: {e}")
                        # Continue with next batch even if one fails
                        continue
            else:
                print(f"  No matching tracks found for playlist '{playlist_name}'")
        
        print("\nSync completed!")

    def check_tracks(self):
        trackslist = self.client.users_likes_tracks()
        for track_short in tqdm(trackslist.tracks, desc="Fetching liked tracks"):
            try:
                track_short.fetch_track()
            except Exception as e:
                print(f"  Removed track {track_short.track_id} from like")
                self.client.users_likes_tracks_remove(track_short.track_id)
                print(f"  Skipping track: {e}")
                continue