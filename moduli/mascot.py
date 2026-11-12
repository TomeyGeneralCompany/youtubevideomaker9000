"""Reusable mascot animation: amplitude-driven talking and complete action poses."""
import array
import math
import os
from pathlib import Path
import subprocess
import tempfile
import wave
from PIL import Image, ImageDraw, ImageFont
VERSION = 'mascot-ready-v4'
from moduli.runtime_profile import animation_directory, background
SHEET = animation_directory() / 'poses.png'

def load_poses(path=SHEET, size=860):
    sheet = Image.open(path).convert('RGBA')
    if sheet.width % 3 or sheet.height % 2:
        raise ValueError('Mascot sheet must have three columns and two rows')
    w, h = (sheet.width // 3, sheet.height // 2)
    return [sheet.crop((i % 3 * w, i // 3 * h, (i % 3 + 1) * w, (i // 3 + 1) * h)).resize((size, size), Image.Resampling.LANCZOS) for i in range(6)]

def speech_energy(audio, fps=30):
    """Measure actual narration RMS; no remote lip-sync service or model required."""
    with wave.open(str(audio), 'rb') as stream:
        if stream.getsampwidth() != 2:
            raise ValueError('Animation expects PCM16 narration')
        rate, channels = (stream.getframerate(), stream.getnchannels())
        values = []
        while True:
            data = stream.readframes(round(rate / fps))
            if not data:
                break
            samples = array.array('h')
            samples.frombytes(data)
            if os.sys.byteorder != 'little':
                samples.byteswap()
            values.append(math.sqrt(sum((x * x for x in samples)) / max(1, len(samples))))
    reference = sorted(values)[int(len(values) * 0.8)] if values else 1
    return [min(1, value / max(250, reference)) for value in values]

def font(size):
    for name in ['assets/font_bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)

def fit_lines(text, width, start=58, max_lines=3):
    import textwrap
    for size in range(start, 23, -2):
        f = font(size)
        words = text.split()
        lines = []
        line = ''
        for word in words:
            attempt = (line + ' ' + word).strip()
            if f.getlength(attempt) > width and line:
                lines.append(line)
                line = word
            else:
                line = attempt
        if line:
            lines.append(line)
        if len(lines) <= max_lines and all((f.getlength(x) <= width for x in lines)):
            return (f, lines)
    return (font(24), textwrap.wrap(text, width=45)[:max_lines])

def stage(title, width=1080, height=1920):
    """Load the selected background and place the supplied headline."""
    im = background(title, width, height)
    if title:
        d = ImageDraw.Draw(im)
        f, lines = fit_lines(title, width - 160)
        for i, line in enumerate(lines):
            d.text((width / 2, 180 + i * (f.size + 10)), line, font=f, fill='#202020', anchor='mm')
    return im

def render_mascot(audio, output, title='', duration=90, fps=30, sheet=SHEET, on_progress=None):
    from moduli.ffmpeg_utils import ffmpeg_path
    poses = load_poses(sheet)
    base = stage(title)
    energies = speech_energy(audio, fps)
    out = Path(output).absolute()
    out.parent.mkdir(parents=True, exist_ok=True)
    puff_start = 75 if duration >= 85 else duration - 3
    command = [ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '1080x1920', '-r', str(fps), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', os.environ.get('X264_PRESET', 'veryfast'), '-crf', '23', '-threads', os.environ.get('FFMPEG_THREADS', '2'), '-pix_fmt', 'yuv420p', '-t', str(duration), str(out)]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            for index in range(round(duration * fps)):
                energy = energies[index] if index < len(energies) else 0
                process.stdin.write(frame_at(base, poses, index / fps, energy, puff_start).tobytes())
                if index % 150 == 0:
                    percent = round(index / (duration * fps) * 75)
                    print(f'[mascot] Animation {percent}% ({index / fps:.0f}s/{duration:.0f}s)', flush=True)
                    if on_progress:
                        on_progress(percent, 'mascot talking')
            process.stdin.close()
            code = process.wait(timeout=300)
            if code:
                errors.seek(0)
                raise RuntimeError(errors.read().decode(errors='replace')[-2000:])
        except Exception:
            process.kill()
            process.wait()
            errors.seek(0)
            details = errors.read().decode(errors='replace')[-2000:]
            if details:
                print(details, flush=True)
            raise
    return str(out)

def mascot_cover(title, output, sheet=SHEET):
    im = stage(title)
    pose = load_poses(sheet)[3]
    im = im.convert('RGBA')
    im.alpha_composite(pose, (110, 475))
    d = ImageDraw.Draw(im)
    f = font(43)
    text = 'GOD BLESS AMERICA'
    d.text(((1080 - f.getlength(text)) / 2, 1510), text, font=f, fill='#f2c55b')
    im.convert('RGB').save(output, quality=92)

def generate_host_audio(content, output):
    """Narrate all words, with a 2.5-second silent cigar beat before the closing."""
    from moduli.audio import genera_audio
    from moduli.shorts import fit_narration
    from moduli.ffmpeg_utils import ffmpeg_path
    script = content['script']
    closing = content.get('closing_script', '').strip()
    if closing and script.rstrip().endswith(closing):
        body = script.rstrip()[:-len(closing)].strip()
    else:
        words = script.split()
        if len(words) < 90:
            raise ValueError('Mascot narration needs a complete 200–250 word script')
        body = ' '.join(words[:-35])
        closing = ' '.join(words[-35:])
    if not body or not closing:
        raise ValueError('Narration needs both a main segment and closing')
    with tempfile.TemporaryDirectory(prefix='mascot-tts_') as root:
        root = Path(root)
        genera_audio(body, str(root / 'body.mp3'))
        genera_audio(closing, str(root / 'closing.mp3'))
        fit_narration(root / 'body.mp3', root / 'body.wav', target=75)
        fit_narration(root / 'closing.mp3', root / 'closing.wav', target=12.5)
        subprocess.run([ffmpeg_path(), '-y', '-nostdin', '-v', 'error', '-i', str(root / 'body.wav'), '-f', 'lavfi', '-t', '2.5', '-i', 'anullsrc=r=48000:cl=stereo', '-i', str(root / 'closing.wav'), '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]', '-map', '[a]', '-ar', '48000', '-ac', '2', '-c:a', 'libmp3lame', '-b:a', '192k', str(output)], check=True, capture_output=True, timeout=180)

from moduli.mascot_walk import install as _install_walking_landscape
_install_walking_landscape(globals())
