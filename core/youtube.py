import os
import requests
from tqdm import tqdm
from ytmusicapi import YTMusic, OAuthCredentials
from typing import List, Tuple
from .track import Track


class YoutubeImporter:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        use_tor: bool = False,
        tor_host: str = "127.0.0.1",
        tor_port: int = 9150,
        headers: str = "browser.json",
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
        session = self._create_session(use_tor, tor_host, tor_port)

        if os.path.exists(headers):
            with open(headers, "r") as f:
                token = f.read()
            self.ytmusic = YTMusic(
                token,
                oauth_credentials=OAuthCredentials(
                    client_id=client_id, client_secret=client_secret
                ),
                requests_session=session,
            )
        else:
            print("Config file does not exist!")

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
                        self.ytmusic.rate_song(result["videoId"], "LIKE")
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
