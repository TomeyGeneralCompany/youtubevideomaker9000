"""Read the settings used by narration publication and background music."""
import json
from pathlib import Path

def carica():
    path = Path('video-preferences.json')
    defaults = {'language': 'english', 'music_volume': 0.1}
    if path.is_file():
        values = json.loads(path.read_text())
        defaults['language'] = values.get('language', values.get('lingua', 'english'))
        defaults['music_volume'] = values.get('music_volume', values.get('musica_volume', 0.1))
    return defaults
load_preferences = carica
