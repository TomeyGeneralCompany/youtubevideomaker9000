"""Read the configured fallback language for YouTube metadata."""
import json
from pathlib import Path


def load_preferences():
    path = Path('video-preferences.json')
    if not path.is_file():
        return {'language': 'english'}
    settings = json.loads(path.read_text(encoding='utf-8'))
    return {'language': settings.get('language', 'english')}
