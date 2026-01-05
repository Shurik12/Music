import argparse
import json
import yaml

from src import YaMusicHandle
from src.ytmusic import YTMusicClient


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Config file {config_path} not found!")
        print("Creating a template config.yaml...")
        create_template_config(config_path)
        exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing config.yaml: {e}")
        exit(1)

def create_template_config(config_path: str):
    """Create a template config file"""
    template = """# Configuration for Yandex Music to YouTube Music transfer
yandex_music:
  token: "YOUR_YANDEX_MUSIC_TOKEN_HERE"

youtube_music:
  client_id: "your_client_id_here"
  client_secret: "your_client_secret_here"
  
tor_proxy:
  enabled: true  # Set to false to disable Tor
  host: "127.0.0.1"
  port: 9150
"""
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(template)
    print(f"Template config created at {config_path}")
    print("Please fill in your credentials and run the script again.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Transfer tracks from Yandex.Music to YouTube Music'
    )
    parser.add_argument(
        '--config', type=str, default='config.yaml', 
        help='Path to config.yaml file'
    )
    parser.add_argument(
        '--output', type=str, default='tracks.json', 
        help='Output json file for transfer results'
    )
    parser.add_argument(
        '--no-tor', action='store_true',
        help='Disable Tor proxy (overrides config)'
    )
    return parser.parse_args()


def move_tracks(
        importer: YaMusicHandle, 
        exporter: YTMusicClient, 
        out_path: str
    ) -> None:
    data = {
        'liked_tracks': [],
        'not_found': [],
        'errors': [],
    }
    
    print('Exporting liked tracks from Yandex Music...')
    tracks = importer.export_liked_tracks()
    tracks.reverse()

    for track in tracks:
        data['liked_tracks'].append({
            'artist': track.artist,
            'name': track.name
        })

    print('Importing liked tracks to Youtube Music...')
    not_found, errors = exporter.import_liked_tracks(tracks)

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


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    
    # Initialize Yandex Music exporter
    yandex_token = config['yandex_music']['token']
    if yandex_token == "YOUR_YANDEX_MUSIC_TOKEN_HERE":
        print("Please update your Yandex Music token in config.yaml")
        exit(1)
    
    importer = YaMusicHandle(yandex_token)
    
    # Tor proxy configuration
    tor_config = config.get('tor_proxy', {})
    use_tor = tor_config.get('enabled', True) and not args.no_tor
    proxy_host = tor_config.get('host', '127.0.0.1')
    proxy_port = tor_config.get('port', 9150)
    
    if use_tor:
        print(f"Using Tor proxy: {proxy_host}:{proxy_port}")
    else:
        print("Tor proxy disabled")

    ytmusic = YTMusicClient(
        client_id = config['youtube_music']['client_id'],
        client_secret = config['youtube_music']['client_secret'],
        use_tor = use_tor,
        tor_host = proxy_host,
        tor_port = proxy_port
    )

    # plylists = ytmusic.get_playlists()
    # ytmusic.print_playlists(plylists)

    tracks = ytmusic.get_track_out_playlist()
    ytmusic.print_tracks(tracks)

    # ytmusic.create_playlist(playlist)
    # move_tracks(importer, exporter, args.output)


if __name__ == '__main__':
    main()