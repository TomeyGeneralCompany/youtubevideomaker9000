"""Resolve selected animation assets and voice settings independently of a channel."""
import json, os
from pathlib import Path

def workspace():
    return Path(os.environ.get('TUBE_WORKSPACE', Path.home() / '.tomey-media')).expanduser().resolve()

def media_profile():
    path = Path(os.environ.get('MEDIA_PROFILE', workspace() / 'media-profile.json')).expanduser()
    return json.loads(path.read_text()) if path.is_file() else {}

def animation_directory():
    value = media_profile().get('animation', {}).get('assets_dir', 'assets/animation')
    p = Path(value).expanduser()
    return p if p.is_absolute() else workspace() / p

def brand_name():
    return str(media_profile().get('brand_name', ''))

def background(title, width, height):
    from PIL import Image, ImageDraw
    settings = media_profile().get('animation', {})
    value = settings.get('background')
    if value:
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = workspace() / p
        return Image.open(p).convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
    return Image.new('RGB', (width, height), settings.get('background_color', '#ffffff'))

def voice_profile():
    path = Path(os.environ.get('VOICE_PROFILE', workspace() / 'voice-profile.json')).expanduser()
    if not path.is_file():
        raise RuntimeError('Select a voice profile in voice-profile.json or VOICE_PROFILE before generating narration.')
    return json.loads(path.read_text())
