"""Locate FFmpeg and FFprobe for both narration and video editing."""
import os
import shutil
import sys
_CANDIDATI_FFMPEG = ['C:\\ffmpeg\\bin\\ffmpeg.exe', 'C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe', 'C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe', '/usr/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/opt/homebrew/bin/ffmpeg']

def ffmpeg_path() -> str:
    """Locate FFmpeg using FFMPEG_PATH, PATH, then known locations; raise FileNotFoundError with setup instructions."""
    env_path = os.environ.get('FFMPEG_PATH')
    if env_path and os.path.exists(env_path):
        return env_path
    if shutil.which('ffmpeg'):
        return 'ffmpeg'
    for p in _CANDIDATI_FFMPEG:
        if os.path.exists(p):
            return p
    raise FileNotFoundError('ffmpeg not found. Install it and add to PATH, or set FFMPEG_PATH=/path/to/ffmpeg')

def ffprobe_path() -> str:
    """Prefer FFprobe beside FFmpeg, otherwise search PATH."""
    try:
        ff = ffmpeg_path()
    except FileNotFoundError:
        return 'ffprobe'
    if ff != 'ffmpeg':
        for nome in ('ffprobe.exe', 'ffprobe'):
            candidato = os.path.join(os.path.dirname(ff), nome)
            if os.path.exists(candidato):
                return candidato
    if shutil.which('ffprobe'):
        return 'ffprobe'
    return 'ffprobe'

def esporta_per_moviepy() -> str | None:
    """Set FFMPEG_BINARY before importing MoviePy so all render paths use the same FFmpeg. Return the selected path or None."""
    if 'moviepy.config' in sys.modules:
        return os.environ.get('FFMPEG_BINARY')
    try:
        percorso = ffmpeg_path()
    except FileNotFoundError:
        return None
    if percorso == 'ffmpeg':
        os.environ.setdefault('FFMPEG_BINARY', 'auto-detect')
    else:
        os.environ['FFMPEG_BINARY'] = percorso
    return os.environ['FFMPEG_BINARY']
