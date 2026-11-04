"""Minimal FFmpeg and music helpers for local mascot composition."""
import os, glob, random
FFMPEG_THREADS = max(1, int(os.environ.get('FFMPEG_THREADS', '2')))
X264_CRF = int(os.environ.get('X264_CRF', '23'))
X264_PRESET = os.environ.get('X264_PRESET', 'fast')
BG_MUSIC_DIR = 'assets/music'
BG_MUSIC_PATH = os.environ.get('BG_MUSIC_PATH', 'assets/music/background.mp3')
BG_MUSIC_VOLUME = 0.1
ALLOWED_MOODS = {'epic', 'chill', 'mysterious', 'upbeat', 'tense'}

def _bg_volume() -> float:
    """Read background music volume from user preferences."""
    try:
        from moduli.preferenze import carica
        vol = float(carica().get('music_volume', BG_MUSIC_VOLUME))
        return max(0.0, min(1.0, vol))
    except Exception:
        return BG_MUSIC_VOLUME

def _pick_music(mood: str | None) -> str | None:
    if mood and mood.lower() in ALLOWED_MOODS:
        tracks = glob.glob(os.path.join(BG_MUSIC_DIR, mood.lower(), '*.mp3'))
        if tracks:
            return random.choice(tracks)
    tracks = glob.glob(os.path.join(BG_MUSIC_DIR, '*.mp3'))
    if tracks:
        return random.choice(tracks)
    if os.path.exists(BG_MUSIC_PATH):
        return BG_MUSIC_PATH
    return None

def _concat_file_line(path: str) -> str:
    safe = os.path.abspath(path).replace('\\', '/').replace("'", "'\\''")
    return f"file '{safe}'\n"

def _timestamp(secondi: float) -> str:
    ms = max(0, int(round(secondi * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
