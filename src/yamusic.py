from yandex_music import Client, Artist
from typing import List
from .track import Track
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