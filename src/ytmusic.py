import os
import requests
from tqdm import tqdm
from ytmusicapi import YTMusic, OAuthCredentials
from typing import List, Dict, Any, Optional, Union, Tuple
import yaml

from src.track import Track


class YTMusicClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        use_tor: bool = False,
        tor_host: str = "127.0.0.1",
        tor_port: int = 9150,
        auth_file: str = "browser.json",
    ):
        """
        Initialize YouTube Music client with optional Tor proxy.

        Args:
            client_id: YouTube Music OAuth client ID
            client_secret: YouTube Music OAuth client secret
            use_tor: Enable Tor proxy
            tor_host: Tor proxy host
            tor_port: Tor proxy port
            auth_file: Path to save/load authentication file
        """
        self.auth_file = auth_file

        # Create session with optional Tor proxy
        session = self._create_session(use_tor, tor_host, tor_port)

        # Initialize YTMusic with OAuth credentials
        if os.path.exists(auth_file):
            # Load existing authentication
            with open(auth_file, "r") as f:
                token = f.read()
            self.ytmusic = YTMusic(token, requests_session=session)
        else:
            # Create new authentication with OAuth
            oauth_credentials = OAuthCredentials(
                client_id=client_id, client_secret=client_secret
            )
            self.ytmusic = YTMusic(
                oauth_credentials=oauth_credentials, requests_session=session
            )
            # Save authentication for future use
            token = self.ytmusic.get_oauth_token()  # type: ignore
            with open(auth_file, "w") as f:
                f.write(token)

        # Test connection
        self._test_connection(session)

    def _create_session(
        self, use_tor: bool, tor_host: str, tor_port: int
    ) -> requests.Session:
        """Create a requests session with optional Tor proxy"""
        session = requests.Session()

        if use_tor:
            proxy_url = f"socks5h://{tor_host}:{tor_port}"
            session.proxies = {"http": proxy_url, "https": proxy_url}
            print(f"Configured Tor proxy: {proxy_url}")

        return session

    def _test_connection(self, session: requests.Session) -> None:
        """Test the connection to verify Tor is working (if enabled)"""
        try:
            if session.proxies:
                # Test Tor connection
                response = session.get(
                    "https://check.torproject.org/api/ip", timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    print(f"✓ Connected via Tor. IP: {data.get('IP')}")
                else:
                    print("⚠ Could not verify Tor connection")
            else:
                print("✓ Connected directly (no proxy)")
        except Exception as e:
            if session.proxies:
                print(f"⚠ Tor connection test failed: {e}")
                print("   Make sure Tor Browser is running if you want to use Tor.")
            else:
                print(f"⚠ Connection test failed: {e}")

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

    def get_api(self) -> YTMusic:
        """Get the underlying ytmusicapi instance"""
        return self.ytmusic

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

    def add_playlist_items(
        self, playlist_id: str, video_ids: List[str]
    ) -> Dict[str, Any]:
        """Add tracks to a playlist"""
        try:
            return self.ytmusic.add_playlist_items(playlist_id, video_ids)  # type: ignore
        except Exception as e:
            print(f"Error adding items to playlist {playlist_id}: {e}")
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
                print(f"Error processing {track.artist} - {track.name}: {e}")

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
            self.add_playlist_items(playlist_info["id"], add_tracks)
