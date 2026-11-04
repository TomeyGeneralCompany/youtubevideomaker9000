"""Reusable mascot animation: amplitude-driven talking and complete action poses."""
import argparse
import array
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import wave
from PIL import Image, ImageDraw, ImageFont
VERSION = 'mascot-ready-v4'
POSES = ('idle', 'talk_small', 'talk_big', 'point', 'puff', 'exhale')
from moduli.runtime_profile import animation_directory, background, brand_name
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

def pose_at(t, energy, puff_start=75.0):
    if puff_start <= t < puff_start + 1.1:
        return 4
    if puff_start + 1.1 <= t < puff_start + 2.5:
        return 5
    if energy < 0.1:
        return 0
    if int(t) % 13 in (4, 5):
        return 3
    return 2 if energy > 0.62 and int(t * 9) % 3 else 1

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

def mouth_sprite(idle, t, energy):
    """Animate only the mouth; hat, glasses, hands and feet stay pixel stable."""
    sprite = idle.copy()
    if energy < 0.1:
        return sprite
    scale = sprite.width / 512
    shape = int(t * 11) % 4
    openness = (0.32, 0.78, 1.0, 0.5)[shape] * min(1, energy / 0.45)
    cx = 285 * scale
    top = 251 * scale
    half = (18 if shape != 3 else 12) * scale
    height = (7 + 23 * openness) * scale
    draw = ImageDraw.Draw(sprite)
    draw.ellipse((cx - half - 3 * scale, top - 2 * scale, cx + half + 3 * scale, top + height + 3 * scale), fill='#ffffff')
    draw.ellipse((cx - half, top, cx + half, top + height), fill='#61091a')
    if height > 14 * scale:
        draw.ellipse((cx - half * 0.48, top + height * 0.68, cx + half * 0.55, top + height * 0.92), fill='#ef4559')
    if shape != 3:
        draw.rounded_rectangle((cx - half * 0.62, top + 2 * scale, cx + half * 0.62, top + 5 * scale), radius=scale, fill='white')
    return sprite

def frame_at(base, poses, t, energy, puff_start=75):
    im = base.copy().convert('RGBA')
    if puff_start <= t < puff_start + 1.1:
        sprite = poses[4]
    elif puff_start + 1.1 <= t < puff_start + 2.5:
        sprite = poses[5]
    else:
        sprite = mouth_sprite(poses[0], t, energy)
    im.alpha_composite(sprite, (110, 475))
    if puff_start + 1.1 <= t < puff_start + 2.5:
        layer = Image.new('RGBA', im.size)
        d = ImageDraw.Draw(layer)
        elapsed = t - puff_start - 1.1
        for k in range(4):
            px = 790 + elapsed * 62 + k * 22
            py = 805 - elapsed * 95 - k * 24
            r = 12 + elapsed * 18 + k * 3
            alpha = round(max(0, 1 - elapsed / 1.6) * 95)
            d.ellipse((px - r, py - r, px + r, py + r), fill=(220, 247, 248, alpha))
        im = Image.alpha_composite(im, layer)
    return im.convert('RGB')

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

def preview(output):
    poses = load_poses(size=520)
    base = stage('MASCOT ANIMATION PREVIEW').resize((648, 1152), Image.Resampling.LANCZOS)
    frames = []
    for i in range(72):
        t = i / 12
        energy = 0 if t < 0.7 else 0.5 + 0.4 * math.sin(t * 14)
        full = frame_at(stage('MASCOT ANIMATION PREVIEW'), load_poses(), t, energy, puff_start=3.1)
        frames.append(full.resize((360, 640), Image.Resampling.LANCZOS))
    frames[0].save(output, save_all=True, append_images=frames[1:], duration=83, loop=0, optimize=False)

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

def write_host_srt(script, path, closing_words=35):
    from moduli.sottotitoli import _timestamp
    words = script.split()
    lines = []
    count = 0
    for section, offset, length in [(words[:-closing_words], 0, 75), (words[-closing_words:], 77.5, 12.5)]:
        for i in range(0, len(section), 6):
            group = section[i:i + 6]
            count += 1
            start = offset + length * i / len(section)
            end = offset + length * (i + len(group)) / len(section)
            lines.append(f"{count}\n{_timestamp(start)} --> {_timestamp(end)}\n{' '.join(group)}\n")
    Path(path).write_text('\n'.join(lines), encoding='utf-8')
    return str(path)
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', required=True)
    args = parser.parse_args()
    preview(args.preview)
from moduli.mascot_walk import install as _install_walking_landscape
_install_walking_landscape(globals())
