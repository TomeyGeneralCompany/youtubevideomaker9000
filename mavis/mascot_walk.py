"""Whole-pose cel animation; no cut-apart mascot limbs."""
import json
import math
from contextvars import ContextVar
from pathlib import Path
from functools import lru_cache
from mavis.runtime_profile import media_profile
from PIL import Image, ImageDraw
VERSION = 'mascot-approved-cels-20261015-r1'

def install(namespace):
    original_stage = namespace['stage']
    asset = Path(namespace['SHEET']).parent / 'walk-cycle.png'

    def stage(title, width=1080, height=1920):
        return original_stage(title, width, height)

    @lru_cache(maxsize=1)
    def cycle():
        sheet = Image.open(asset).convert('RGBA')
        if sheet.width % 4 or sheet.height % 2:
            raise ValueError('Walking sheet must have four columns and two rows')
        w, h = (sheet.width // 4, sheet.height // 2)
        return [sheet.crop((i % 4 * w, i // 4 * h, (i % 4 + 1) * w, (i // 4 + 1) * h)) for i in range(8)]

    active = ContextVar('animation_inputs', default=None)

    def render_inputs():
        for load in (cycle, puff_cycle, landmarks):
            load.cache_clear()
        path = asset.parent / 'action-cycle.json'
        marks = json.loads(path.read_text()) if path.is_file() else None
        if marks is None:
            marks = []
            for sprite in puff_cycle():
                box = sprite.getchannel('A').point(lambda x: 255 if x > 128 else 0).getbbox()
                marks.append({'mouth': [sprite.width * 0.5, sprite.height * 0.35], 'floor': box[3]})
        return media_profile().get('animation', {}), marks, {}

    def frame_at(base, poses, t, energy, puff_start=75):
        im = base.copy().convert('RGBA')
        d = ImageDraw.Draw(im)
        width, height = im.size
        settings, action_marks, resized = active.get() or render_inputs()
        ground = int(settings.get('ground_y', 1330))
        puff_start = float(settings.get('action_start', puff_start))
        puff = puff_start <= t < puff_start + 2.5
        travel = (min(t, puff_start) + max(0, t - puff_start - 2.5)) * 85
        if settings.get('moving_landscape', False):
            points = [(x, ground + 28 + 12 * math.sin((x + travel) / 510)) for x in range(42, width - 40, 10)]
            d.polygon([(42, 1450)] + points + [(width - 42, 1450)], fill='#346c45')
            d.line(points, fill='#c6b57e', width=65)
            for k in range(-2, 8):
                x = round(k * 235 - travel % 235)
                if 60 < x < width - 65:
                    d.line((x, ground - 120, x, ground - 35), fill='#f2dfab', width=10)
                    d.line((max(43, x - 235), ground - 90, x, ground - 90), fill='#f2dfab', width=6)
        clock = min(t, puff_start) if puff else t - max(0, min(2.5, t - puff_start))
        index = 0 if puff else int(clock * 12) % 8
        puff_index = 0 if t - puff_start < 0.15 else 1 if t - puff_start < 1.1 else 2
        sprite = puff_cycle()[puff_index] if puff else cycle()[index]
        marks = action_marks[puff_index] if puff else landmarks()[index]
        voiced = not puff and energy > 0.1
        if voiced:
            sprite = sprite.copy()
            cx, cy = marks['mouth']
            a = min(1, energy / 0.5)
            opening = (0.35, 0.8, 1, 0.5)[int(t * 11) % 4] * a
            sd = ImageDraw.Draw(sprite)
            rx = 12
            ry = 2 + 4 * opening
            sd.ellipse((cx - rx - 2, cy - 2, cx + rx + 2, cy + 2 * ry + 2), fill='white')
            sd.ellipse((cx - rx, cy, cx + rx, cy + 2 * ry), fill='#61091a')
            sd.rounded_rectangle((cx - 7, cy + 1, cx + 7, cy + 4), radius=1, fill='white')
        target_height = 760
        factor = target_height / sprite.height
        key = (puff, puff_index if puff else index)
        if voiced:
            sprite = sprite.resize((round(sprite.width * factor), target_height), Image.Resampling.LANCZOS)
        else:
            if key not in resized:
                resized[key] = sprite.resize((round(sprite.width * factor), target_height), Image.Resampling.LANCZOS)
            sprite = resized[key]
        x = round((width - sprite.width) / 2)
        y = round(ground - marks['floor'] * factor)
        d.ellipse((width / 2 - 205, ground - 12, width / 2 + 205, ground + 20), fill=(24, 61, 41, 120))
        im.alpha_composite(sprite, (x, y))
        if settings.get('action_smoke', False) and puff_start + 1.1 <= t < puff_start + 2.5:
            elapsed = t - puff_start - 1.1
            layer = Image.new('RGBA', im.size)
            smoke = ImageDraw.Draw(layer)
            cx, cy = marks['mouth']
            cx = x + cx * factor
            cy = y + cy * factor
            for k in range(5):
                age = elapsed - k * 0.14
                if age < 0:
                    continue
                px = cx + age * 150
                py = cy - age * 100
                r = 12 + age * 25
                smoke.ellipse((px - r, py - r, px + r, py + r), fill=(240, 248, 244, int(115 * max(0, 1 - age / 1.5))))
            im = Image.alpha_composite(im, layer)
        return im.convert('RGB')

    @lru_cache(maxsize=1)
    def puff_cycle():
        sheet = Image.open(asset.parent / 'puff-cycle.png').convert('RGBA')
        w = sheet.width // 3
        return [sheet.crop((i * w, 0, (i + 1) * w, sheet.height)) for i in range(3)]

    @lru_cache(maxsize=1)
    def landmarks():
        import json
        return json.loads(asset.with_suffix('.json').read_text())
    namespace['stage'] = stage
    namespace['frame_at'] = frame_at
    namespace['VERSION'] = VERSION
    original_render = namespace['render_mascot']
    import functools

    @functools.wraps(original_render)
    def verified_render(*args, **kwargs):
        verify_assets()
        if namespace.get('frame_at') is not frame_at or namespace.get('stage') is not stage:
            raise RuntimeError('Approved animation was overridden; rendering blocked')
        token = active.set(render_inputs())
        try:
            return original_render(*args, **kwargs)
        finally:
            active.reset(token)
    namespace['render_mascot'] = verified_render

    def verify_assets():
        import hashlib, json
        manifest = json.loads((asset.parent / 'approved-animation-sha256.json').read_text())
        for name, digest in manifest.items():
            path = asset.parent / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError('Approved animation file missing or changed: ' + name)
    verify_assets()
