import requests
from tqdm import tqdm
from ytmusicapi import YTMusic
from typing import List, Dict, Any, Optional, Set, Union, Tuple
import yaml
from pathlib import Path
import os
import logging
import yt_dlp
from datetime import datetime

# Create logs directory if it doesn't exist
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Configure logging to write to log folder
log_filename = logs_dir / f"download_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # Only show warnings and errors in console
console_handler.setFormatter(logging.Formatter('%(message)s'))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Create a separate logger for file-only logs
file_logger = logging.getLogger(f"{__name__}.file")
file_logger.setLevel(logging.INFO)
file_logger.addHandler(file_handler)
file_logger.propagate = False  # Don't send to console


class YtdlpLogger:
    """Route yt-dlp messages into the file log and collect errors for callers.

    When passed as yt-dlp's ``logger`` param, yt-dlp sends errors via ``error``,
    warnings via ``warning`` and regular screen output via ``debug``. Without it,
    failures are silently swallowed by quiet + ignoreerrors (the caller only sees
    a missing file with no reason).
    """

    def __init__(self, echo: bool = False) -> None:
        self.echo = echo
        self.errors: List[str] = []

    def debug(self, msg: str) -> None:
        if self.echo:
            print(msg)

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        file_logger.warning(f"yt-dlp: {msg}")

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        file_logger.error(f"yt-dlp: {msg}")


from src.track import Track


class YTMusicClient:
    def __init__(
        self,
    ):
        session = requests.Session()
        session.proxies = {
            "http": "socks5://127.0.0.1:1080",
            "https": "socks5://127.0.0.1:1080"
        }
        session.trust_env = False

        self.ytmusic = YTMusic(
            auth="browser.json",
            requests_session=session,
        )
        self._check_auth()

    def _check_auth(self) -> None:
        """Probe the account endpoint; expired browser.json silently returns logged-out data."""
        try:
            info = self.ytmusic.get_account_info()
        except KeyError:
            print(
                "WARNING: YouTube Music authentication is expired or invalid (browser.json).\n"
                "         Library/playlist/liked-track methods will return empty results.\n"
                "         Re-export it: log into https://music.youtube.com in a browser, copy a\n"
                "         'browse' request's headers from DevTools, then run: ytmusicapi browser"
            )
            file_logger.warning(
                "YouTube Music auth check failed: browser.json expired or invalid (logged-out response)"
            )
            return
        except Exception as e:
            print(
                f"WARNING: Could not verify YouTube Music authentication ({type(e).__name__}: {e}).\n"
                "         Check network/proxy (SOCKS5 127.0.0.1:1080) and browser.json."
            )
            file_logger.warning(f"YouTube Music auth check failed: {type(e).__name__}: {e}")
            return

        account = info.get("accountName", "unknown")
        print(f"YouTube Music authenticated as: {account}")
        file_logger.info(f"YouTube Music auth check passed: authenticated as {account}")

    def import_liked_tracks(
        self, tracks: List[Track]
    ) -> Tuple[List[Track], List[Track]]:
        not_found: List[Track] = []
        errors: List[Track] = []

        with tqdm(total=len(tracks), position=0, desc="Import tracks") as pbar:
            with tqdm(total=0, bar_format="{desc}", position=1) as trank_log:
                for track in tracks:
                    query = f"{track.artist} {track.name}"

                    try:
                        results = self.ytmusic.search(query, filter="songs")
                    except Exception as e:
                        errors.append(track)
                        pbar.write(f"Search error: {query}, {e}")
                        pbar.update(1)
                        continue

                    if not results:
                        not_found.append(track)
                        pbar.update(1)
                        continue

                    result = self._get_best_result(results, track)
                    try:
                        self.ytmusic.rate_song(result["videoId"], "LIKE")  # type: ignore
                    except Exception as e:
                        errors.append(track)
                        pbar.write(f"Error: {track.artist} - {track.name}, {e}")

                    pbar.update(1)
                    trank_log.set_description_str(f"{track.artist} - {track.name}")

        return not_found, errors

    def _get_best_result(self, results: List[dict], track: Track) -> dict:
        songs = []
        for result in results:
            if "videoId" not in result.keys():
                continue
            if result.get("category") == "Top result":
                return result
            if result.get("title") == track.name:
                return result
            songs.append(result)
        if len(songs) == 0:
            return results[0]
        return songs[0]

    # ===== Playlist Management Methods =====

    def get_playlists(self, limit: Optional[int] = 100) -> List[Dict[str, Any]]:
        """
        Retrieves the playlists in the user's library.

        Args:
            limit: Number of playlists to retrieve. None retrieves them all.

        Returns:
            List of owned playlists.
        """
        try:
            playlists = self.ytmusic.get_library_playlists(limit=limit)
            return playlists
        except Exception as e:
            print(f"Error getting library playlists: {e}")
            return []

    def print_playlists(self, playlists: List[Dict[str, Any]]):
        for playlist in playlists:
            print(f"{playlist["title"]}: {playlist["playlistId"]}")

    def create_playlist(
        self,
        title: str,
        description: str = str(),
        privacy_status: str = "PUBLIC",
        video_ids: Optional[List[str]] = None,
        source_playlist: Optional[str] = None,
    ) -> Union[str, Dict[str, Any]]:
        """
        Creates a new empty playlist and returns its id.

        Args:
            title: Playlist title
            description: Playlist description
            privacy_status: Playlists can be PUBLIC, PRIVATE, or UNLISTED. Default: PRIVATE
            video_ids: IDs of songs to create the playlist with
            source_playlist: Another playlist whose songs should be added to the new playlist

        Returns:
            ID of the YouTube playlist or full response if there was an error
        """
        try:
            result = self.ytmusic.create_playlist(
                title=title,
                description=description,
                privacy_status=privacy_status,
                video_ids=video_ids,
                source_playlist=source_playlist,
            )
            return result
        except Exception as e:
            error_msg = f"Exception creating playlist: {type(e).__name__}: {e}"
            return {"status": "ERROR", "error": error_msg}

    def get_playlist(self, playlist_id: str, limit: int = 5000) -> Dict[str, Any]:
        """Get playlist details and tracks"""
        try:
            return self.ytmusic.get_playlist(playlist_id, limit)
        except Exception as e:
            print(f"Error getting playlist {playlist_id}: {e}")
            return {}
        
    def get_playlist_artists(self, playlist: Dict[str, Any]) -> Set[str]:
        artists = set()
        for track in playlist["tracks"]:
            for artist in track["artists"]:
                artists.add(artist["name"])
        return artists

    def add_playlist_items(
        self, playlist_id: str, video_ids: List[str]
    ) -> Dict[str, Any]:
        """Add tracks to a playlist"""
        try:
            file_logger.info(f"Add {len(video_ids)} tracks to playlist {playlist_id}")
            return self.ytmusic.add_playlist_items(playlist_id, video_ids)  # type: ignore
        except Exception as e:
            file_logger.error(f"Error adding items to playlist {playlist_id}: {e}")
            return {}

    def delete_playlist(self, playlist_id: str) -> Dict[str, Any]:
        """Delete a playlist"""
        try:
            return self.ytmusic.delete_playlist(playlist_id)  # type: ignore
        except Exception as e:
            error_msg = f"Error deleting playlist {playlist_id}: {e}"
            return {"status": "ERROR", "error": error_msg}

    def edit_playlist(
        self,
        playlist_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        privacy_status: Optional[str] = None,
        move_item: Optional[Tuple[int, int]] = None,
    ) -> Dict[str, Any]:
        """Edit playlist metadata"""
        try:
            return self.ytmusic.edit_playlist(
                playlist_id,
                title,
                description,
                privacy_status,
                move_item,  # type: ignore
            )
        except Exception as e:
            error_msg = f"Error editing playlist {playlist_id}: {e}"
            return {"status": "ERROR", "error": error_msg}

    def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """Get all tracks from a playlist"""
        playlist = self.get_playlist(playlist_id, limit=5000)  # Large limit to get all
        return playlist.get("tracks", [])

    def search_and_add_to_playlist(
        self, playlist_id: str, tracks: List[Track], max_results: int = 5
    ) -> Tuple[int, int, int]:
        """
        Search for tracks and add them to a playlist.

        Args:
            playlist_id: Target playlist ID
            tracks: List of Track objects to search for
            max_results: Maximum number of search results to consider per track

        Returns:
            Tuple of (added_count, not_found_count, error_count)
        """
        added = 0
        not_found = 0
        errors = 0

        for track in tracks:
            query = f"{track.artist} {track.name}"

            try:
                results = self.ytmusic.search(query, filter="songs", limit=max_results)

                if not results:
                    not_found += 1
                    continue

                # Get the best result
                best_result = None
                for result in results:
                    if "videoId" in result:
                        best_result = result
                        break

                if best_result:
                    self.add_playlist_items(playlist_id, [best_result["videoId"]])
                    added += 1
                else:
                    not_found += 1

            except Exception as e:
                errors += 1
                file_logger.error(f"Error processing {track.artist} - {track.name}: {e}")

        return added, not_found, errors

    def get_track_out_playlist(self) -> List[Dict[str, Any]]:
        """Get tracks from liked music that are not in any mapped playlist"""
        skip_track_videoId = set()
        like_playlist = {}
        playlists = self.get_playlists()

        for playlist_metadata in tqdm(
            playlists,
            desc="Getting playlists",
            total=len(playlists),
            unit="playlists",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ):
            if playlist_metadata["playlistId"] == "SE":
                continue
            else:
                playlist = self.get_playlist(playlist_metadata["playlistId"])
                if playlist["id"] == "LM":
                    like_playlist = playlist
                else:
                    skip_track_videoId.update(
                        [track["videoId"] for track in playlist["tracks"]]
                    )
        track_out_playlist = []

        for track in tqdm(
            like_playlist["tracks"],
            desc="Choosing tracks out playlist",
            total=len(like_playlist["tracks"]),
            unit="tracks",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
        ):
            if track["videoId"] not in skip_track_videoId:
                track_out_playlist.append(track)
        
        file_logger.info(f"{len(track_out_playlist)} tracks out playlist")
        print(f"{len(track_out_playlist)} tracks out playlist")

        return track_out_playlist

    def print_tracks(self, tracks: List[Dict[str, Any]]):
        total_tracks = len(tracks)
        with open("tracks.txt", "w") as fw:
            for track in tqdm(
                tracks,
                desc="Writing tracks to file",
                total=total_tracks,
                unit="tracks",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
            ):
                fw.write(
                    f"{track['artists'][0]['name']}\t{track['title']}\t{track['videoId']}\n"
                )

        print(f"Successfully wrote {total_tracks} tracks to tracks.txt")

    def distribute_tracks(self):
        with open("playlists_map.yaml", "r", encoding="utf-8") as f:
            playlists_map = yaml.safe_load(f)

        track_out_playlist = self.get_track_out_playlist()

        for playlist_info in playlists_map.values():
            add_tracks = []
            for track in track_out_playlist:
                if track["artists"][0]["name"] in playlist_info["artists"]:
                    add_tracks.append(track["videoId"])
            
            file_logger.info(f"Add {len(add_tracks)} tracks to playlist {playlist_info['id']}")
            if (len(add_tracks)):
                self.add_playlist_items(playlist_info["id"], add_tracks)
    
    def update_playlists_map(self, output_file: str = "playlists_map_updated.yaml"):
        """
        Update playlists_map.yaml file with current playlists and their artists.
        Excludes playlists with IDs in ["LM", "SE"].
        
        Args:
            output_file: Path to save the updated playlists map
        """
        print("Fetching playlists...")
        playlists = self.get_playlists()
        
        if not playlists:
            print("No playlists found.")
            return
        
        # Filter out excluded playlists
        excluded_ids = ["LM", "SE"]
        filtered_playlists = [ p for p in playlists if p.get("playlistId") not in excluded_ids ]
        
        print(f"Found {len(filtered_playlists)} playlists (excluding LM and SE)")
        
        playlists_map = {}
        
        for playlist_metadata in tqdm(filtered_playlists, desc="Processing playlists"):
            
            playlist = self.get_playlist(playlist_metadata["playlistId"])
            artists = self.get_playlist_artists(playlist)
            key = playlist_metadata["title"].replace(":", " -")  # Avoid YAML key issues with colons
            
            playlists_map[key] = {
                "id": playlist["id"],
                "artists": sorted(list(artists))
            }
        
        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(playlists_map, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        
        print(f"\n✓ Updated playlists map saved to {output_file}")
        print(f"Total playlists in map: {len(playlists_map)}")

    
    def load_playlist_tracks_map(self, yaml_file: str) -> Dict[str, bool]:
        """
        Load a previously saved playlist tracks map from YAML file.
        
        Args:
            yaml_file: Path to the YAML file
            
        Returns:
            Dictionary mapping video_id -> exists (bool)
        """
        with open(yaml_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if "tracks" in data:
            return data["tracks"]
        else:
            return data

    # ===== Download Methods =====

    def download_track(
        self, 
        video_id: str, 
        output_path: str = "downloads",
        format_type: str = "mp3",
        quality: str = "best",
        progress_hooks: Optional[List[callable]] = None,
        quiet: bool = True
    ) -> Optional[str]:
        """
        Download a single track from YouTube using yt-dlp.
        """
        import sys
        from contextlib import contextmanager
        
        @contextmanager
        def suppress_output():
            """Context manager to suppress stdout and stderr"""
            with open(os.devnull, 'w') as devnull:
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = devnull
                sys.stderr = devnull
                try:
                    yield
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Create output directory if it doesn't exist
        Path(output_path).mkdir(parents=True, exist_ok=True)
        
        ydl_logger = YtdlpLogger(echo=not quiet)
        
        # Configure yt-dlp options
        ydl_opts = {
            # Proxy configuration
            'proxy': 'socks5://127.0.0.1:1080',
            
            # Headers
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0',
            'referer': 'https://music.youtube.com',
            
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_type,
                'preferredquality': '0' if quality == 'best' else '192',
            }],
            
            'outtmpl': os.path.join(output_path, '%(artist)s - %(title)s.%(ext)s'),
            'concurrent_fragments': 6,
            'progress': not quiet,  # Disable progress if quiet
            'quiet': quiet,
            'no_warnings': quiet,
            'no_color': quiet,
            'ignoreerrors': True,
            'extract_flat': False,
            'logger': ydl_logger,
            # YouTube needs a JS runtime (node >= 20 or deno) plus the EJS solver
            # script, which is fetched from GitHub on first use and then cached.
            'js_runtimes': {'node': {}, 'deno': {}},
            'remote_components': ['ejs:github'],
        }
        
        # Override audio quality
        quality_map = {
            'best': '0',
            'high': '192',
            'medium': '128',
            'low': '64'
        }
        ydl_opts['postprocessors'][0]['preferredquality'] = quality_map.get(quality, '0')
        
        # Add progress hooks if provided
        if progress_hooks:
            ydl_opts['progress_hooks'] = progress_hooks
        
        try:
            # Use context manager to suppress ALL output if quiet
            if quiet:
                with suppress_output():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        filename = ydl.prepare_filename(info) if info else None
            else:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info) if info else None
        except Exception as e:
            file_logger.error(f"Error downloading video {video_id}: {e}")
            return None

        if filename is None:
            reason = "; ".join(ydl_logger.errors) or "unknown yt-dlp error (no details reported)"
            file_logger.error(f"  yt-dlp failed for {video_id}: {reason}")
            return None

        filename = os.path.splitext(filename)[0] + f'.{format_type}'
        if not os.path.exists(filename):
            reason = "; ".join(ydl_logger.errors) or "file was not created"
            file_logger.error(f"  yt-dlp did not create {video_id} file ({filename}): {reason}")
            return None

        file_logger.info(f"Downloaded: {filename}")
        return filename
        
    def download_all_playlists(
        self,
        base_output_path: str = "downloads",
        format_type: str = "mp3",
        quality: str = "best",
        skip_existing: bool = True,
        playlist_limit: Optional[int] = 100
    ) -> Dict[str, Dict[str, Any]]:
        """
        Download all tracks from all user playlists, organizing by playlist.
        Checks track existence using video IDs and stores a map for each playlist.
        
        Args:
            base_output_path: Base directory for downloads (creates playlist subfolders)
            format_type: Audio format (mp3, m4a, etc.)
            quality: Audio quality (best, high, medium, low)
            skip_existing: If True, skip already downloaded tracks using video ID tracking
            playlist_limit: Maximum number of playlists to fetch
                
        Returns:
            Dictionary with playlist names as keys and download statistics as values
        """
        # Get all playlists
        print("\nFetching playlists...")
        playlists = self.get_playlists(limit=playlist_limit)
        
        if not playlists:
            print("No playlists found.")
            return {}
        
        # Filter out excluded playlists
        excluded_ids = ["LM", "SE"]
        playlists = [p for p in playlists if p.get("playlistId") not in excluded_ids]
        
        print(f"Found {len(playlists)} playlists")
        file_logger.info(f"Found {len(playlists)} playlists to download")
        
        # Statistics for each playlist
        download_stats = {}
        
        # Create a main progress bar for playlists
        playlist_pbar = tqdm(
            total=len(playlists), 
            desc="Overall progress", 
            unit="playlist",
            position=0,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
        )
        
        # Process each playlist
        for playlist_idx, playlist_metadata in enumerate(playlists, 1):
            playlist_id = playlist_metadata["playlistId"]
            playlist_title = playlist_metadata["title"]
            
            # Update playlist progress bar description
            playlist_pbar.set_description(f"Playlist {playlist_idx}/{len(playlists)}: {playlist_title[:50]}")
            
            # Sanitize playlist name for folder name
            safe_playlist_name = "".join(c for c in playlist_title if c not in '/\\:*?"<>|')
            playlist_output_path = os.path.join(base_output_path, safe_playlist_name)
            
            # Create playlist-specific track map file path
            track_map_file_path = Path(playlist_output_path) / f"track_map_{safe_playlist_name}.yaml"
            
            file_logger.info(f"\nProcessing playlist: {playlist_title} (ID: {playlist_id})")
            
            # Get tracks in this playlist
            tracks = self.get_playlist_tracks(playlist_id)
            
            if not tracks:
                file_logger.warning(f"  No tracks found in playlist: {playlist_title}")
                download_stats[playlist_title] = {
                    "total": 0,
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 0,
                    "path": playlist_output_path,
                    "track_map_file": str(track_map_file_path)
                }
                playlist_pbar.update(1)
                continue
            
            file_logger.info(f"  Found {len(tracks)} tracks in playlist")
            
            # Load existing track map for this playlist if it exists
            track_map = {}
            existing_video_ids = set()
            
            if skip_existing and os.path.exists(track_map_file_path):
                try:
                    with open(track_map_file_path, 'r', encoding='utf-8') as f:
                        track_map = yaml.safe_load(f) or {}
                    
                    # Extract video IDs that have valid files
                    for video_id, track_info in track_map.items():
                        file_path = track_info.get("file_path")
                        if file_path and os.path.exists(file_path):
                            existing_video_ids.add(video_id)
                        else:
                            # File missing, mark for re-download
                            file_logger.warning(f"  Missing file for video ID {video_id}, will re-download")
                            existing_video_ids.discard(video_id)
                    
                    file_logger.info(f"  Loaded track map with {len(track_map)} tracks, {len(existing_video_ids)} exist on disk")
                    if len(existing_video_ids) > 0:
                        print(f"  ✓ Loaded track map: {len(existing_video_ids)} already downloaded tracks found")
                except Exception as e:
                    print(f"  Warning: Could not load track map: {e}")
                    track_map = {}
            
            # Statistics for this playlist
            stats = {
                "total": len(tracks),
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "path": playlist_output_path,
                "track_map_file": str(track_map_file_path),
                "video_ids": {}  # Store mapping of video_id -> download status for this session
            }
            
            # Create output directory if it doesn't exist
            Path(playlist_output_path).mkdir(parents=True, exist_ok=True)
            
            # Create a sub-progress bar for tracks in this playlist
            track_pbar = tqdm(
                total=len(tracks), 
                desc=f"  [{playlist_title[:40]}] Downloading tracks", 
                unit="track", 
                position=1,
                leave=False,
                bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
            )
            
            for track in tracks:
                # Get track info
                video_id = track.get("videoId")
                if not video_id:
                    stats["failed"] += 1
                    file_logger.warning(f"  No video_id for track: {track.get('title', 'Unknown')}")
                    track_pbar.update(1)
                    continue
                
                # Get artist and title for logging
                artists = track.get("artists", [])
                artist_name = artists[0].get("name", "Unknown Artist") if artists else "Unknown Artist"
                title = track.get("title", "Unknown Title")
                
                # Update track progress bar with current track info
                track_pbar.set_description(f"  [{playlist_title[:30]}] {artist_name[:20]} - {title[:30]}")
                
                # Check if track already exists by video ID in this playlist's track map
                if skip_existing and video_id in existing_video_ids:
                    stats["skipped"] += 1
                    stats["video_ids"][video_id] = {
                        "status": "skipped", 
                        "file": track_map.get(video_id, {}).get("file_path", "unknown"),
                        "title": title,
                        "artist": artist_name
                    }
                    file_logger.info(f"  ✓ Skipped (exists by video ID): {artist_name} - {title} (ID: {video_id})")
                    track_pbar.update(1)
                    continue
                
                # Log to file before downloading
                file_logger.info(f"  ↓ Downloading: {artist_name} - {title} (ID: {video_id})")
                
                # Download the track
                downloaded_file = self.download_track(
                    video_id=video_id,
                    output_path=playlist_output_path,
                    format_type=format_type,
                    quality=quality,
                    progress_hooks=None,
                    quiet=True
                )
                
                if downloaded_file and os.path.exists(downloaded_file):
                    stats["downloaded"] += 1
                    
                    # Store in track map
                    track_map[video_id] = {
                        "video_id": video_id,
                        "title": title,
                        "artist": artist_name,
                        "file_path": downloaded_file,
                        "filename": os.path.basename(downloaded_file),
                        "playlist": playlist_title,
                        "playlist_id": playlist_id,
                        "downloaded_at": datetime.now().isoformat()
                    }
                    
                    stats["video_ids"][video_id] = {
                        "status": "downloaded", 
                        "file": downloaded_file,
                        "title": title,
                        "artist": artist_name
                    }
                    
                    # Add to existing_video_ids for this playlist
                    existing_video_ids.add(video_id)
                    
                    file_logger.info(f"  ✓ Downloaded: {artist_name} - {title} -> {os.path.basename(downloaded_file)}")
                else:
                    stats["failed"] += 1
                    stats["video_ids"][video_id] = {
                        "status": "failed", 
                        "error": "download failed",
                        "title": title,
                        "artist": artist_name
                    }
                    file_logger.error(f"  ✗ Failed: {artist_name} - {title} (ID: {video_id})")
                
                # Save track map periodically (every 5 tracks or after each download)
                if len(stats["video_ids"]) % 5 == 0:
                    try:
                        with open(track_map_file_path, 'w', encoding='utf-8') as f:
                            yaml.dump(track_map, f, allow_unicode=True, default_flow_style=False)
                    except Exception as e:
                        file_logger.error(f"Error saving track map: {e}")
                
                track_pbar.update(1)
            
            # Close track progress bar
            track_pbar.close()
            
            # Final save of track map for this playlist
            try:
                with open(track_map_file_path, 'w', encoding='utf-8') as f:
                    yaml.dump(track_map, f, allow_unicode=True, default_flow_style=False)
                print(f"  ✓ Track map saved to: {track_map_file_path}")
                file_logger.info(f"Track map saved with {len(track_map)} tracks")
            except Exception as e:
                file_logger.error(f"Error saving final track map: {e}")
            
            download_stats[playlist_title] = stats
            
            # Update playlist progress bar with summary
            playlist_pbar.set_postfix_str(f"✓ {stats['downloaded']}↓ {stats['skipped']}⏭ {stats['failed']}✗")
            
            # Log playlist summary to file
            file_logger.info(f"  Playlist '{playlist_title}': {stats['downloaded']} downloaded, "
                        f"{stats['skipped']} skipped, {stats['failed']} failed")
            
            # Print a clean line for this playlist summary
            print(f"\n✓ Playlist '{playlist_title}': {stats['downloaded']} downloaded, "
                f"{stats['skipped']} skipped, {stats['failed']} failed")
            
            playlist_pbar.update(1)
        
        # Close main progress bar
        playlist_pbar.close()
        
        # Print and log overall summary
        print("\n" + "="*50)
        print("DOWNLOAD SUMMARY")
        print("="*50)
        
        file_logger.info("\n" + "="*50)
        file_logger.info("DOWNLOAD SUMMARY")
        file_logger.info("="*50)
        
        total_tracks = 0
        total_downloaded = 0
        total_skipped = 0
        total_failed = 0
        
        for playlist_name, stats in download_stats.items():
            print(f"\n{playlist_name}:")
            print(f"  Total: {stats['total']}")
            print(f"  Downloaded: {stats['downloaded']}")
            print(f"  Skipped: {stats['skipped']}")
            print(f"  Failed: {stats['failed']}")
            print(f"  Path: {stats['path']}")
            print(f"  Track Map: {stats['track_map_file']}")
            
            file_logger.info(f"\n{playlist_name}:")
            file_logger.info(f"  Total: {stats['total']}")
            file_logger.info(f"  Downloaded: {stats['downloaded']}")
            file_logger.info(f"  Skipped: {stats['skipped']}")
            file_logger.info(f"  Failed: {stats['failed']}")
            file_logger.info(f"  Path: {stats['path']}")
            file_logger.info(f"  Track Map: {stats['track_map_file']}")
            
            total_tracks += stats['total']
            total_downloaded += stats['downloaded']
            total_skipped += stats['skipped']
            total_failed += stats['failed']
        
        print("\n" + "="*50)
        print("TOTALS:")
        print(f"  Total playlists: {len(download_stats)}")
        print(f"  Total tracks: {total_tracks}")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total skipped: {total_skipped}")
        print(f"  Total failed: {total_failed}")
        print("="*50)
        
        file_logger.info("\n" + "="*50)
        file_logger.info("TOTALS:")
        file_logger.info(f"  Total playlists: {len(download_stats)}")
        file_logger.info(f"  Total tracks: {total_tracks}")
        file_logger.info(f"  Total downloaded: {total_downloaded}")
        file_logger.info(f"  Total skipped: {total_skipped}")
        file_logger.info(f"  Total failed: {total_failed}")
        file_logger.info("="*50)
        file_logger.info(f"Log file saved to: {log_filename}")
        
        print(f"\n✓ Detailed log saved to: {log_filename}")
        
        return download_stats