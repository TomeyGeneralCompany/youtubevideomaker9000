from moduli.runtime_profile import animation_directory, brand_name
'Paul Revere Media: fixed-format Shorts and offline recovery primitives.'
import hashlib
import json
import math
import os
from pathlib import Path
import random
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
            from moduli.quota_control import defer_if_daily_quota
            defer_if_daily_quota(exc)
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

def cached_image(prompt, fetch):
    """Retry network requests, then use cache or an original Americana graphic."""
    from PIL import Image, ImageDraw
    directory = Path('cache/pollinations_images')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(('portrait-v2|' + prompt).encode()).hexdigest()[:20] + '.png')
    if path.exists():
        try:
            with Image.open(path) as im:
                return im.convert('RGB')
        except OSError:
            path.unlink()
    try:
        image = retry(fetch)
        if not isinstance(image, Image.Image):
            raise ValueError('Image provider returned no usable image')
    except Exception as exc:
        print(f'[images] Provider unavailable ({type(exc).__name__}); using local artwork/cache', flush=True)
        candidates = sorted(directory.glob('*.png'))
        random.Random(prompt).shuffle(candidates)
        for candidate in candidates:
            try:
                with Image.open(candidate) as im:
                    return im.convert('RGB')
            except OSError:
                continue
        image = Image.new('RGB', (WIDTH, HEIGHT), '#091e42')
        draw = ImageDraw.Draw(image)
        for i in range(13):
            y = int(i * HEIGHT / 13)
            draw.rectangle((0, y, WIDTH, int((i + 1) * HEIGHT / 13)), fill='#b31942' if i % 2 == 0 else '#f1f0e8')
        draw.rectangle((0, 0, 650, 950), fill='#0a3161')
        for row in range(9):
            for col in range(6 if row % 2 == 0 else 5):
                cx, cy = (55 + col * 105 + (50 if row % 2 else 0), 65 + row * 100)
                points = [(cx + (28 if k % 2 == 0 else 12) * math.cos(-math.pi / 2 + k * math.pi / 5), cy + (28 if k % 2 == 0 else 12) * math.sin(-math.pi / 2 + k * math.pi / 5)) for k in range(10)]
                draw.polygon(points, fill='#fff8d2')
    tmp = path.with_suffix('.tmp.png')
    image.save(tmp)
    os.replace(tmp, path)
    return image.convert('RGB')

def _ass_time(seconds):
    centis = round(seconds * 100)
    h, centis = divmod(centis, 360000)
    m, centis = divmod(centis, 6000)
    s, c = divmod(centis, 100)
    return f'{h}:{m:02}:{s:02}.{c:02}'

def write_ass(script, path, cigar_beat=False, closing_words=35):
    import textwrap
    words = (script or '').split()
    if not words:
        raise ValueError('Caption script is empty')
    header = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Brand,DejaVu Sans,42,&H0057D7FF,&H0000D7FF,&H00101326,&H90000000,-1,0,0,0,100,100,0,0,1,3,1,8,100,180,160,1\nStyle: Main,DejaVu Sans,58,&H00FFFFFF,&H0000D7FF,&H00101326,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,100,230,460,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    lines = [header, f'Dialogue: 1,0:00:00.00,0:01:30.00,Brand,,0,0,0,,{brand_name()}\n']
    sections = [(words, 0.0, DURATION)]
    if cigar_beat:
        sections = [(words[:-closing_words], 0.0, 75.0), (words[-closing_words:], 77.5, 12.5)]
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

def local_music(path):
    """An original low-volume dramatic chord/drum bed; no downloaded music."""
    import array
    rate = 16000
    samples = array.array('h')
    rng = random.Random(1776)
    chords = [(110, 130.81, 164.81), (87.31, 110, 130.81), (98, 123.47, 146.83), (82.41, 110, 130.81)]
    for n in range(int(rate * DURATION)):
        t = n / rate
        chord = chords[int(t / 6) % len(chords)]
        beat = t % 0.6
        kick = math.sin(2 * math.pi * (55 * beat + 28 * (1 - math.exp(-beat * 20)))) * math.exp(-beat * 22)
        hit = rng.uniform(-1, 1) * math.exp(-beat * 45)
        swell = 0.7 + 0.3 * math.sin(t * 0.5)
        tone = sum((math.sin(2 * math.pi * f * t) for f in chord)) / 3
        fade = min(1, t / 2, (DURATION - t) / 3)
        samples.append(int(6500 * fade * (0.45 * tone * swell + 0.4 * kick + 0.08 * hit)))
    if os.sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return str(path)

def render_short(audio_path, keywords, clip_paths, output_path, mood=None, on_progress=None, custom_music=None, captions_text=None):
    from moduli import montaggio as m
    destination = Path(output_path).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    mascot_mode = os.environ.get('PAUL_REVERE_VIDEO_MODE', 'mascot') == 'mascot'
    files, durations = m._filtra_clip_leggibili([clip_paths[k] for k in keywords if k in clip_paths]) if not mascot_mode else ([], {})
    if not mascot_mode and (not files):
        raise ValueError('No readable visual clips; cannot render Short')
    sequence = m._build_clip_sequence(files, 30, m._clip_prioritarie(keywords, clip_paths, files)) if not mascot_mode else []
    with tempfile.TemporaryDirectory(prefix='paul-revere-short_') as root:
        root = Path(root)
        narration = fit_narration(audio_path, root / 'narration.wav')
        ass = root / 'captions.ass'
        write_ass(captions_text, ass, cigar_beat=mascot_mode, closing_words=int(os.environ.get('PAUL_REVERE_CLOSING_WORDS', '35')))
        segments = []
        if mascot_mode:
            from moduli.mascot import render_mascot
            title = os.environ.get('PAUL_REVERE_CURRENT_TITLE', '')
            layer = destination.parent / 'mascot-layer.mkv'
            metadata = destination.parent / 'mascot-layer.json'
            signature = hashlib.sha256(Path(narration).read_bytes() + (animation_directory() / 'poses.png').read_bytes() + title.encode() + b'mascot-approved-cels-20261015-r1').hexdigest()
            reusable = False
            if layer.exists() and metadata.exists():
                try:
                    info = probe(layer)
                    reusable = json.loads(metadata.read_text()).get('signature') == signature and abs(float(info['format']['duration']) - 90) < 1 / FPS
                except (ValueError, OSError, subprocess.CalledProcessError):
                    pass
            if not reusable:
                render_mascot(narration, root / 'mascot.mkv', title=title, on_progress=on_progress)
                import shutil
                shutil.copyfile(root / 'mascot.mkv', layer)
                if abs(float(probe(layer)['format']['duration']) - 90) > 1 / FPS:
                    raise ValueError('Incomplete mascot animation layer')
                atomic_json(metadata, {'signature': signature})
            segments = [layer]
        for i, source in enumerate(sequence):
            target = root / f'segment_{i:03}.mkv'

            def render_segment():
                m._render_segment_ffmpeg(source, str(target), i * 3, 3, None, durations[source])
                info = probe(target)
                streams = [x for x in info['streams'] if x['codec_type'] == 'video']
                if not streams or abs(float(info['format'].get('duration', 0)) - 3) > 1 / FPS:
                    raise ValueError('Encoder returned an incomplete visual segment')
            retry(render_segment)
            segments.append(target)
            if on_progress:
                on_progress(round((i + 1) / 30 * 80), 'vertical segments')
        listing = root / 'segments.txt'
        listing.write_text(''.join((m._concat_file_line(str(s)) for s in segments)))
        music = custom_music if custom_music and Path(custom_music).exists() else m._pick_music(mood)
        music = music or local_music(root / 'dramatic-bed.wav')
        filters = root / 'filter.txt'
        filters.write_text(f'[0:v]ass=captions.ass[v];[1:a]volume=1[n];[2:a]volume={m._bg_volume()},atrim=duration=90[b];[n][b]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=duration=90[a]')
        tmp = root / 'complete.mp4'
        command = [m._ffmpeg(), '-y', '-nostdin', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing), '-i', narration, '-stream_loop', '-1', '-i', str(Path(music).absolute()), '-filter_complex_script', str(filters), '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', m.X264_PRESET, '-crf', str(m.X264_CRF), '-threads', str(m.FFMPEG_THREADS), '-pix_fmt', 'yuv420p', '-r', '30', '-t', '90', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(tmp)]
        try:
            subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=1800)
            validate_short(tmp)
            import shutil
            partial = destination.with_name(destination.stem + '.partial.mp4')
            shutil.copyfile(tmp, partial)
            validate_short(partial)
            os.replace(partial, destination)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.stderr.decode(errors='replace')[-2000:]) from exc
        finally:
            if tmp.exists():
                tmp.unlink()
    if on_progress:
        on_progress(100, '90-second Short validated')
