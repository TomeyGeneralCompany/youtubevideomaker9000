from moduli.runtime_profile import animation_directory, brand_name, media_profile, workspace
'Paul Revere Media: fixed-format Shorts and offline recovery primitives.'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import wave
DURATION = 90.0
WIDTH, HEIGHT, FPS = (1080, 1920, 30)

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def retry(fn, attempts=3, delay=2):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status in (400, 401, 402, 403, 404) or attempt == attempts - 1:
                raise
            time.sleep(min(30, delay * 2 ** attempt))

def probe(path):
    from moduli.ffmpeg_utils import ffprobe_path
    result = subprocess.run([ffprobe_path(), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)

def validate_short(path):
    info = probe(path)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    audios = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or not audios:
        raise ValueError('Short must contain one video stream and narration audio')
    stream = videos[0]
    if (stream['width'], stream['height']) != (WIDTH, HEIGHT):
        raise ValueError('Short must be 1080 x 1920')
    if stream.get('codec_name') != 'h264' or stream.get('pix_fmt') != 'yuv420p':
        raise ValueError('Short must be H.264/yuv420p')
    if stream.get('sample_aspect_ratio', '1:1') != '1:1':
        raise ValueError('Short must use square pixels')
    for seconds in (float(info['format']['duration']), float(stream.get('duration', 0))):
        if abs(seconds - DURATION) > 1 / FPS:
            raise ValueError(f'Short duration is {seconds:.3f}s; expected 90s')
    if abs(float(audios[0].get('duration', 0)) - DURATION) > 0.06:
        raise ValueError('Narration stream does not span 90 seconds')
    return info

def fit_narration(source, dest, target=90):
    """Fit all supplied words to 90 seconds without cutting or rewriting them."""
    from moduli.ffmpeg_utils import ffmpeg_path
    info = probe(source)
    duration = float(info['format']['duration'])
    tempo = duration / target
    if not 0.7 <= tempo <= 1.4:
        raise ValueError(f'Narration is {duration:.1f}s. Supply roughly 200–240 words; fitting this script would make speech too slow or fast. No words were removed.')
    subprocess.run([ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-i', str(source), '-af', f'atempo={tempo:.8f},apad,atrim=duration={target},asetpts=N/SR/TB', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(dest)], check=True, capture_output=True, timeout=120)
    return str(dest)

def _ass_time(seconds):
    centis = round(seconds * 100)
    h, centis = divmod(centis, 360000)
    m, centis = divmod(centis, 6000)
    s, c = divmod(centis, 100)
    return f'{h}:{m:02}:{s:02}.{c:02}'

def write_ass(script, path, cigar_beat=False, closing_words=35, duration=DURATION):
    import textwrap
    words = (script or '').split()
    if not words:
        raise ValueError('Caption script is empty')
    header = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Brand,DejaVu Sans,42,&H0057D7FF,&H0000D7FF,&H00101326,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,8,100,180,160,1\nStyle: Main,DejaVu Sans,58,&H00FFFFFF,&H0000D7FF,&H00101326,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,100,230,460,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    lines = [header, f'Dialogue: 1,0:00:00.00,0:01:30.00,Brand,,0,0,0,,{brand_name()}\n']
    sections = [(words, 0.0, duration)]
    if cigar_beat:
        sections = [(words[:-closing_words], 0.0, 75.0), (words[-closing_words:], 77.5, duration - 77.5)]
    for section, offset, length in sections:
        if not section:
            continue
        for i in range(0, len(section), 6):
            group = section[i:i + 6]
            text = ' '.join(group).replace('\\', '/').replace('{', '(').replace('}', ')')
            text = '\\N'.join(textwrap.wrap(text, width=23, break_long_words=True))
            start, end = (offset + length * i / len(section), offset + length * (i + len(group)) / len(section))
            lines.append(f'Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Main,,0,0,0,,{text}\n')
    Path(path).write_text(''.join(lines), encoding='utf-8')

def _prepared_pcm(path):
    try:
        with wave.open(str(path), 'rb') as wav:
            return (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (
                2, 2, 48000, int(DURATION * 48000))
    except (EOFError, wave.Error):
        return False


def _layer_signature(narration, title):
    profile = media_profile()
    settings = profile.get('animation', {})
    assets = animation_directory()
    files = [Path(narration), *(assets / name for name in (
        'poses.png', 'walk-cycle.png', 'walk-cycle.json', 'puff-cycle.png', 'action-cycle.json')),
        workspace() / 'assets/font_bold.ttf']
    if settings.get('background'):
        files.append(workspace() / Path(settings['background']).expanduser())
    stamp = {
        'version': 2, 'title': title, 'profile': profile,
        'preset': os.getenv('X264_PRESET', 'veryfast'), 'threads': os.getenv('FFMPEG_THREADS', '2'),
        'inputs': [],
    }
    for index, path in enumerate(files):
        digest = None
        if path.is_file():
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        stamp['inputs'].append((str(path) if index else 'narration', digest))
    return hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()


def render_short(audio_path, output_path, mood=None, on_progress=None, custom_music=None, captions_text=None):
    from moduli.ffmpeg_utils import ffmpeg_path
    destination = Path(output_path).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.short-', dir=destination.parent) as root:
        root = Path(root)
        audio = Path(audio_path).resolve()
        narration = str(audio) if _prepared_pcm(audio) else fit_narration(audio, root / 'narration.wav')
        ass = root / 'captions.ass'
        if captions_text:
            write_ass(captions_text, ass, cigar_beat=True, closing_words=int(os.environ.get('PAUL_REVERE_CLOSING_WORDS', '35')), duration=DURATION)
        from moduli.mascot import render_mascot
        title = os.environ.get('PAUL_REVERE_CURRENT_TITLE', '')
        layer = destination.parent / 'mascot-layer.mkv'
        metadata = destination.parent / 'mascot-layer.json'
        signature = _layer_signature(narration, title)
        reusable = False
        if layer.exists() and metadata.exists():
            try:
                info = probe(layer)
                reusable = json.loads(metadata.read_text()).get('signature') == signature and abs(float(info['format']['duration']) - 90) < 1 / FPS
            except (ValueError, OSError, subprocess.CalledProcessError):
                pass
        if not reusable:
            render_mascot(narration, root / 'mascot.mkv', title=title, on_progress=on_progress)
            if abs(float(probe(root / 'mascot.mkv')['format']['duration']) - DURATION) > 1 / FPS:
                raise ValueError('Incomplete mascot animation layer')
            os.replace(root / 'mascot.mkv', layer)
            atomic_json(metadata, {'signature': signature})
        music = Path(custom_music).expanduser().resolve() if custom_music else None
        if music and not music.is_file():
            raise ValueError(f'Music file does not exist: {music}')
        inputs = ['-i', str(layer), '-i', narration]
        filters = []
        video_map = '0:v'
        if captions_text:
            filters.append('[0:v]ass=captions.ass[v]')
            video_map = '[v]'
        audio_source = '[1:a]'
        if music:
            inputs.extend(['-stream_loop', '-1', '-i', str(music)])
            volume = float(os.getenv('TUBE_MUSIC_VOLUME', '0.1'))
            if not 0 <= volume <= 1:
                raise ValueError('Music volume must be between 0 and 1.')
            filters.extend([f'[2:a]volume={volume},atrim=duration=90[bed]',
                            '[1:a][bed]amix=inputs=2:duration=first:normalize=0[mix]'])
            audio_source = '[mix]'
        filters.append(audio_source + 'loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=duration=90[a]')
        tmp = root / 'complete.mp4'
        command = [ffmpeg_path(), '-y', '-nostdin', '-v', 'error', *inputs,
                   '-filter_complex', ';'.join(filters), '-map', video_map, '-map', '[a]',
                   '-c:v', 'libx264', '-preset', os.getenv('X264_PRESET', 'fast'),
                   '-crf', os.getenv('X264_CRF', '23'), '-threads', os.getenv('FFMPEG_THREADS', '2'),
                   '-pix_fmt', 'yuv420p', '-r', '30', '-t', '90', '-c:a', 'aac', '-b:a', '192k',
                   '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(tmp)]
        try:
            subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=1800)
            info = validate_short(tmp)
            os.replace(tmp, destination)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr.decode(errors='replace')[-2000:]) from exc
    if on_progress:
        on_progress(100, '90-second Short validated')
    return info
