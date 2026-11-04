"""Generate AI video clips alongside or instead of Pexels stock footage. Hybrid mode generates the opening clips; VIDEO_AI_MAX_CLIPS caps generation spending. Cache entries include prompt and model. Provider credentials remain in .env."""
import hashlib
import os
import time
import requests
CACHE_DIR = os.environ.get('VIDEO_AI_CACHE_DIR', 'cache/ai_video')
PROVIDER_DEFAULTS = {'pollinations': {'etichetta': 'Pollinations + FFmpeg (free)', 'env_key': 'POLLINATIONS_TOKEN', 'modello': 'flux', 'hint': 'no API key required', 'nota': 'generates free images and animates them locally with FFmpeg.'}, 'replicate': {'etichetta': 'Replicate', 'env_key': 'REPLICATE_API_TOKEN', 'modello': 'wan-video/wan-2.1-t2v-480p', 'hint': 'replicate.com/account/api-tokens'}, 'fal': {'etichetta': 'fal.ai', 'env_key': 'FAL_KEY', 'modello': 'fal-ai/ltx-video', 'hint': 'fal.ai/dashboard/keys'}, 'luma': {'etichetta': 'Luma Dream Machine', 'env_key': 'LUMA_API_KEY', 'modello': 'ray-flash-2', 'hint': 'lumalabs.ai/dream-machine/api/keys'}, 'openrouter': {'etichetta': 'OpenRouter (animated image)', 'env_key': 'OPENROUTER_API_KEY', 'modello': 'google/gemini-2.5-flash-image', 'hint': 'openrouter.ai/keys', 'nota': 'generates an image and animates camera movement: cheaper than video models, but without motion inside the scene. Requires FFmpeg.'}}
PROVIDER_IMMAGINE = ('openrouter', 'pollinations')
SORGENTI = ('pexels', 'hybrid', 'ai')

class VideoAIError(RuntimeError):
    """Clip generation failure; callers may fall back to Pexels."""

def sorgente_video() -> str:
    valore = (os.environ.get('VIDEO_SOURCE') or 'pexels').strip().lower()
    return valore if valore in SORGENTI else 'pexels'

def provider() -> str:
    valore = (os.environ.get('VIDEO_AI_PROVIDER') or 'replicate').strip().lower()
    return valore if valore in PROVIDER_DEFAULTS else 'replicate'

def modello() -> str:
    scelto = (os.environ.get('VIDEO_AI_MODEL') or '').strip()
    return scelto or PROVIDER_DEFAULTS[provider()]['modello']

def _chiave() -> str:
    return os.environ.get(PROVIDER_DEFAULTS[provider()]['env_key'], '').strip()

def _intero(nome: str, default: int) -> int:
    try:
        return int(os.environ.get(nome, default))
    except (TypeError, ValueError):
        return default

def max_clip() -> int:
    """Maximum generated clips per video, used as a spending limit."""
    return max(0, _intero('VIDEO_AI_MAX_CLIPS', 6))

def _timeout() -> int:
    return max(60, _intero('VIDEO_AI_TIMEOUT', 420))

def _parallele() -> int:
    return max(1, min(4, _intero('VIDEO_AI_PARALLELE', 2)))

def configurato() -> tuple[bool, str]:
    """Return readiness and a reason for setup checks and the interface."""
    if sorgente_video() == 'pexels':
        return (False, 'VIDEO_SOURCE=pexels — AI generation disabled')
    conf = PROVIDER_DEFAULTS[provider()]
    if provider() != 'pollinations' and (not _chiave()):
        return (False, f"{conf['env_key']} missing for {conf['etichetta']}")
    if max_clip() <= 0:
        return (False, 'VIDEO_AI_MAX_CLIPS=0 — no clips would be generated')
    return (True, f"{conf['etichetta']} — model {modello()}")
_NEGATIVI = 'no text, no captions, no watermark, no logo, no subtitles, no distorted faces, no extra limbs'

def costruisci_prompt(keyword: str, stile: str='') -> str:
    """Turn a stock search keyword into a video prompt including framing, movement and lighting."""
    keyword = ' '.join((keyword or '').split())
    stile = (stile or os.environ.get('VIDEO_AI_STILE', '') or 'cinematic').strip()
    if provider() in PROVIDER_IMMAGINE:
        return f'{keyword}. Cinematic film still, {stile}, shallow depth of field, natural volumetric lighting, photorealistic, 16:9 widescreen, ultra detailed. {_NEGATIVI}.'
    return f'{keyword}. Cinematic b-roll shot, {stile}, shallow depth of field, slow deliberate camera movement, natural volumetric lighting, photorealistic, 16:9, high detail. {_NEGATIVI}.'

def _stile_utente() -> str:
    try:
        from moduli.preferenze import carica
        return (carica().get('clip_style') or '').strip()
    except Exception:
        return ''

def _percorso_cache(prompt: str) -> str:
    """Index generated clips by prompt and model to avoid paying again on a resumed job."""
    impronta = hashlib.sha256(f'{provider()}|{modello()}|{prompt}'.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f'ai_{impronta}.mp4')

def _scarica(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    parziale = dest + '.part'
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(parziale, 'wb') as f:
                for blocco in r.iter_content(chunk_size=65536):
                    if blocco:
                        f.write(blocco)
        if os.path.getsize(parziale) < 10000:
            raise VideoAIError('video file is too small; download incomplete')
        os.replace(parziale, dest)
    except Exception:
        try:
            os.remove(parziale)
        except OSError:
            pass
        raise

def _genera_replicate(prompt: str, durata: int) -> str:
    token = _chiave()
    testa = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    corpo = {'input': {'prompt': prompt, 'num_frames': 81, 'aspect_ratio': '16:9'}}
    r = requests.post(f'https://api.replicate.com/v1/models/{modello()}/predictions', headers=testa, json=corpo, timeout=60)
    if r.status_code == 422:
        r = requests.post(f'https://api.replicate.com/v1/models/{modello()}/predictions', headers=testa, json={'input': {'prompt': prompt}}, timeout=60)
    r.raise_for_status()
    dati = r.json()
    scadenza = time.time() + _timeout()
    while dati.get('status') in ('starting', 'processing'):
        if time.time() > scadenza:
            raise VideoAIError(f'timed out after {_timeout()}s')
        time.sleep(4)
        p = requests.get(dati['urls']['get'], headers=testa, timeout=30)
        p.raise_for_status()
        dati = p.json()
    if dati.get('status') != 'succeeded':
        raise VideoAIError(f"{dati.get('status')}: {str(dati.get('error'))[:160]}")
    uscita = dati.get('output')
    if isinstance(uscita, list):
        uscita = uscita[0] if uscita else None
    if not isinstance(uscita, str):
        raise VideoAIError('no video URL in the Replicate response')
    return uscita

def _genera_fal(prompt: str, durata: int) -> str:
    testa = {'Authorization': f'Key {_chiave()}', 'Content-Type': 'application/json'}
    r = requests.post(f'https://queue.fal.run/{modello()}', headers=testa, json={'prompt': prompt}, timeout=60)
    r.raise_for_status()
    coda = r.json()
    stato_url = coda.get('status_url')
    risposta_url = coda.get('response_url')
    if not stato_url or not risposta_url:
        raise VideoAIError('fal.ai response has no status_url')
    scadenza = time.time() + _timeout()
    while True:
        if time.time() > scadenza:
            raise VideoAIError(f'timed out after {_timeout()}s')
        time.sleep(4)
        s = requests.get(stato_url, headers=testa, timeout=30)
        s.raise_for_status()
        stato = s.json().get('status')
        if stato == 'COMPLETED':
            break
        if stato in ('FAILED', 'ERROR'):
            raise VideoAIError(f'generation failed ({stato})')
    finale = requests.get(risposta_url, headers=testa, timeout=60)
    finale.raise_for_status()
    dati = finale.json()
    video = dati.get('video') or {}
    url = video.get('url') if isinstance(video, dict) else None
    if not url:
        raise VideoAIError('no video URL in the fal.ai response')
    return url

def _genera_luma(prompt: str, durata: int) -> str:
    testa = {'Authorization': f'Bearer {_chiave()}', 'Content-Type': 'application/json'}
    corpo = {'prompt': prompt, 'model': modello(), 'resolution': '720p', 'duration': f'{max(5, durata)}s', 'aspect_ratio': '16:9'}
    r = requests.post('https://api.lumalabs.ai/dream-machine/v1/generations', headers=testa, json=corpo, timeout=60)
    r.raise_for_status()
    gen_id = r.json().get('id')
    if not gen_id:
        raise VideoAIError('Luma response has no generation ID')
    scadenza = time.time() + _timeout()
    while True:
        if time.time() > scadenza:
            raise VideoAIError(f'timed out after {_timeout()}s')
        time.sleep(4)
        s = requests.get(f'https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}', headers=testa, timeout=30)
        s.raise_for_status()
        dati = s.json()
        stato = dati.get('state')
        if stato == 'completed':
            url = (dati.get('assets') or {}).get('video')
            if not url:
                raise VideoAIError('generation completed without video')
            return url
        if stato == 'failed':
            raise VideoAIError(str(dati.get('failure_reason'))[:160])

def _risoluzione() -> tuple[int, int, int]:
    """Match editing resolution so generated clips do not require upscaling."""
    larghezza = max(640, _intero('VIDEO_WIDTH', 1920))
    altezza = max(360, _intero('VIDEO_HEIGHT', 1080))
    fps = max(12, _intero('VIDEO_FPS', 30))
    return (larghezza - larghezza % 2, altezza - altezza % 2, fps)

def _immagine_openrouter(prompt: str) -> bytes:
    testa = {'Authorization': f'Bearer {_chiave()}', 'Content-Type': 'application/json', 'HTTP-Referer': 'tube-assistant', 'X-Title': 'tube-assistant'}
    corpo = {'model': modello(), 'messages': [{'role': 'user', 'content': prompt}], 'modalities': ['image', 'text']}
    r = requests.post('https://openrouter.ai/api/v1/chat/completions', headers=testa, json=corpo, timeout=min(300, _timeout()))
    r.raise_for_status()
    dati = r.json()
    if dati.get('error'):
        raise VideoAIError(str(dati['error'])[:160])
    scelte = dati.get('choices') or []
    messaggio = scelte[0].get('message') or {} if scelte else {}
    immagini = messaggio.get('images') or []
    url = None
    for voce in immagini:
        if isinstance(voce, str):
            url = voce
        elif isinstance(voce, dict):
            campo = voce.get('image_url')
            url = campo.get('url') if isinstance(campo, dict) else campo
        if url:
            break
    if not url:
        raise VideoAIError(f'model {modello()} returned no images — OpenRouter requires an image-output model (for example google/gemini-2.5-flash-image)')
    if url.startswith('data:'):
        import base64
        try:
            return base64.b64decode(url.split(',', 1)[1])
        except (IndexError, ValueError) as e:
            raise VideoAIError(f'unreadable data URI: {e}') from e
    img = requests.get(url, timeout=120)
    img.raise_for_status()
    return img.content

def _movimento(prompt: str, fotogrammi: int) -> str:
    """Choose deterministic camera motion from the prompt, varying motion between clips."""
    zoom_max = 1.18
    passo = round((zoom_max - 1.0) / max(1, fotogrammi - 1), 6)
    centro_x, centro_y = ('iw/2-(iw/zoom/2)', 'ih/2-(ih/zoom/2)')
    avanzamento = f'(on/{max(1, fotogrammi - 1)})'
    quale = int(hashlib.sha256(prompt.encode()).hexdigest(), 16) % 4
    if quale == 0:
        return f"z='min(zoom+{passo},{zoom_max})':x='{centro_x}':y='{centro_y}'"
    if quale == 1:
        return f"z='if(eq(on,0),{zoom_max},max(1.0,zoom-{passo}))':x='{centro_x}':y='{centro_y}'"
    if quale == 2:
        return f"z='{zoom_max}':x='(iw-iw/zoom)*{avanzamento}':y='{centro_y}'"
    return f"z='{zoom_max}':x='(iw-iw/zoom)*(1-{avanzamento})':y='{centro_y}'"

def _clip_da_immagine(dati: bytes, durata: int, prompt: str, dest: str) -> str:
    """Animate a still image with camera movement using FFmpeg."""
    import subprocess
    from moduli.ffmpeg_utils import ffmpeg_path
    larghezza, altezza, fps = _risoluzione()
    durata = max(2, int(durata or 5))
    fotogrammi = durata * fps
    grande_w, grande_h = (larghezza * 2, altezza * 2)
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    sorgente = dest + '.png'
    parziale = dest + '.part.mp4'
    with open(sorgente, 'wb') as f:
        f.write(dati)
    filtro = f'scale={grande_w}:{grande_h}:force_original_aspect_ratio=increase,crop={grande_w}:{grande_h},zoompan={_movimento(prompt, fotogrammi)}:d=1:s={larghezza}x{altezza}:fps={fps},format=yuv420p'
    comando = [ffmpeg_path(), '-y', '-loop', '1', '-i', sorgente, '-t', str(durata), '-vf', filtro, '-r', str(fps), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-an', '-movflags', '+faststart', parziale]
    try:
        esito = subprocess.run(comando, capture_output=True, text=True, timeout=max(120, durata * 30))
        if esito.returncode != 0 or not os.path.exists(parziale):
            coda = (esito.stderr or '').strip().splitlines()[-3:]
            raise VideoAIError('FFmpeg did not create the clip: ' + ' | '.join(coda))
        if os.path.getsize(parziale) < 10000:
            raise VideoAIError('generated clip is empty')
        os.replace(parziale, dest)
        return dest
    except FileNotFoundError as e:
        raise VideoAIError('FFmpeg not found: required to animate images') from e
    except subprocess.TimeoutExpired as e:
        raise VideoAIError('FFmpeg timed out while animating the image') from e
    finally:
        for scarto in (sorgente, parziale):
            try:
                os.remove(scarto)
            except OSError:
                pass

def _genera_pollinations(prompt: str, durata: int) -> str:
    """Generate a Pollinations image and animate it locally with FFmpeg."""
    from io import BytesIO
    from moduli.thumbnail import _fetch_image_pollinations
    from pathlib import Path
    import hashlib
    import random
    import requests
    from PIL import Image, ImageEnhance, ImageOps
    image_cache = Path('cache/pollinations_images')
    image_cache.mkdir(parents=True, exist_ok=True)
    image_path = image_cache / (hashlib.sha256(prompt.encode()).hexdigest()[:20] + '.png')
    if image_path.exists():
        img = Image.open(image_path).convert('RGB')
    else:
        try:
            img = _fetch_image_pollinations(prompt).convert('RGB')
            img.save(image_path)
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 402:
                raise
            available = list(image_cache.glob('*.png'))
            if not available:
                raise
            rng = random.Random(prompt)
            img = Image.open(rng.choice(available)).convert('RGB')
            img = ImageOps.mirror(img) if rng.randrange(2) else img
            img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.85, 1.2))
            print('[Pollinations] Credit limit reached; using cached image variation.', flush=True)
    buf = BytesIO()
    img.save(buf, format='PNG')
    return _clip_da_immagine(buf.getvalue(), durata, prompt, _percorso_cache(prompt))

def _genera_openrouter(prompt: str, durata: int) -> str:
    """Return a local path rather than a URL; assemble the clip locally."""
    return _clip_da_immagine(_immagine_openrouter(prompt), durata, prompt, _percorso_cache(prompt))
_GENERATORI = {'pollinations': _genera_pollinations, 'replicate': _genera_replicate, 'fal': _genera_fal, 'luma': _genera_luma, 'openrouter': _genera_openrouter}

def genera_clip(keyword: str, durata: int=5, stile: str='') -> str:
    """Generate or retrieve one cached clip for the keyword. Raise VideoAIError on failure so callers can use Pexels."""
    pronto, motivo = configurato()
    if not pronto:
        raise VideoAIError(motivo)
    prompt = costruisci_prompt(keyword, stile or _stile_utente())
    dest = _percorso_cache(prompt)
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        return dest
    genera = _GENERATORI[provider()]
    try:
        url = genera(prompt, durata)
    except VideoAIError:
        raise
    except requests.HTTPError as e:
        risposta = getattr(e, 'response', None)
        dettaglio = risposta.text[:200] if risposta is not None else str(e)
        codice = risposta.status_code if risposta is not None else '?'
        if codice in (401, 403):
            raise VideoAIError(f"API key {PROVIDER_DEFAULTS[provider()]['env_key']} rifiutata ({codice})") from e
        if codice == 402:
            raise VideoAIError('video provider credits exhausted') from e
        raise VideoAIError(f'HTTP {codice}: {dettaglio}') from e
    except Exception as e:
        raise VideoAIError(str(e)[:200]) from e
    if not str(url).lower().startswith('http'):
        if not os.path.exists(url) or os.path.getsize(url) < 10000:
            raise VideoAIError('generated clip is invalid')
        if os.path.abspath(url) != os.path.abspath(dest):
            os.replace(url, dest)
        return dest
    _scarica(url, dest)
    return dest

def genera_pool(keywords: list[str], quante: int, durata: int=5, log=print) -> list[str]:
    """Generate up to the requested number of distinct clips in keyword order, prioritizing the beginning of the script."""
    quante = min(quante, max_clip(), len(keywords or []))
    if quante <= 0:
        return []
    pronto, motivo = configurato()
    if not pronto:
        log(f'  → AI generation unavailable: {motivo}')
        return []
    conf = PROVIDER_DEFAULTS[provider()]
    log(f"  → Genero {quante} clips with {conf['etichetta']} ({modello()})")
    stile = _stile_utente()
    scelte = list(keywords)[:quante]
    prodotte: dict[int, str] = {}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=1 if provider() == 'pollinations' else _parallele()) as pool:
        futuri = {pool.submit(genera_clip, kw, durata, stile): (i, kw) for i, kw in enumerate(scelte)}
        for futuro in as_completed(futuri):
            indice, kw = futuri[futuro]
            try:
                prodotte[indice] = futuro.result()
                log(f'     ✓ [{indice + 1}/{quante}] {kw}')
            except VideoAIError as e:
                log(f'     ✗ [{indice + 1}/{quante}] {kw}: {e}')
    return [prodotte[i] for i in sorted(prodotte)]

def riassunto() -> str:
    """Return a status summary for the interface and setup checks."""
    sorgente = sorgente_video()
    if sorgente == 'pexels':
        return 'clip stock da Pexels'
    pronto, motivo = configurato()
    etichetta = 'AI only' if sorgente == 'ai' else f'hybrid (max {max_clip()} clip AI)'
    return f'{etichetta} — {motivo}' if pronto else f'{etichetta} — NOT ready: {motivo}'
