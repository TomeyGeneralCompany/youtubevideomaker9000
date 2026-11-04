import os
import json
import hashlib
import random
import re
import sys
import requests
CACHE_DIR = 'cache/pexels'
PEXELS_SEARCH = 'https://api.pexels.com/videos/search'
INDEX_PATH = os.path.join(CACHE_DIR, 'index.json')
MAX_DOWNLOAD_BYTES = int(os.environ.get('MAX_CLIP_DOWNLOAD_MB', '250')) * 1024 * 1024
MIN_CLIP_SECONDS = float(os.environ.get('MIN_CLIP_SECONDS', '5'))
PEXELS_PER_PAGE_MAX = 80

def _filtra_durata(videos: list) -> list:
    """Prefer clips meeting MIN_CLIP_SECONDS; retain the original list if filtering would leave no clips."""
    lunghe = [v for v in videos if (v.get('duration') or 0) >= MIN_CLIP_SECONDS]
    return lunghe if lunghe else videos

def _tocca(path: str) -> None:
    """Refresh the modification time of a reused cached clip so active clips are not evicted before unused ones."""
    try:
        os.utime(path, None)
    except OSError:
        pass

def _parole_query(keyword: str) -> list[str]:
    """Extract meaningful words that identify the requested scene."""
    parole = [p for p in re.findall('[a-z]+', (keyword or '').lower()) if len(p) > 2 and p not in _STOPWORD_TAG]
    return list(dict.fromkeys(parole))

def _slug_pexels(video: dict) -> set[str]:
    """Extract scene words from the Pexels page slug; the video endpoint does not expose tags or alternative text."""
    url = (video.get('url') or '').lower()
    slug = url.rstrip('/').rsplit('/', 1)[-1]
    return {p for p in re.split('[^a-z]+', slug) if len(p) > 2}

def _punteggio_rilevanza(video: dict, parole: list[str]) -> int:
    """Score clips by meaningful query words in their descriptions, avoiding unrelated results from broad searches."""
    if not parole:
        return 0
    slug = _slug_pexels(video)
    punti = 0
    for p in parole:
        if any((p == s or (len(p) > 4 and p in s) or (len(s) > 4 and s in p) for s in slug)):
            punti += 1
    return punti

def _ordina_per_rilevanza(videos: list, keyword: str) -> list:
    """Prioritize clips naming the subject; retain Pexels order for equal scores."""
    parole = _parole_query(keyword)
    if not parole:
        return videos
    decorati = [(-_punteggio_rilevanza(v, parole), i, v) for i, v in enumerate(videos)]
    decorati.sort(key=lambda t: (t[0], t[1]))
    return [v for _, _, v in decorati]

def _load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        try:
            with open(INDEX_PATH, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _save_index(index: dict) -> None:
    """Write the cache index atomically so interruptions do not leave truncated JSON."""
    tmp = INDEX_PATH + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        os.replace(tmp, INDEX_PATH)
    except OSError as e:
        print(f'[assets] cache index was not saved: {e}', flush=True)
        try:
            os.remove(tmp)
        except OSError:
            pass

def _cache_path(keyword: str) -> str:
    slug = hashlib.md5(keyword.encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f'{slug}.mp4')

def _cache_path_id(pexels_id) -> str:
    """Return the cache path for a distinct Pexels video ID."""
    return os.path.join(CACHE_DIR, f'pex_{pexels_id}.mp4')

def _existing_variant(path: str) -> str | None:
    for p in (path.replace('.mp4', '_720p.mp4'), path.replace('.mp4', '_1080p.mp4'), path):
        if os.path.exists(p):
            return p
    return None

def _cache_path_1080p(keyword: str) -> str:
    return _cache_path(keyword).replace('.mp4', '_1080p.mp4')

def _cache_variants(keyword: str) -> list[str]:
    base = _cache_path(keyword)
    return [base.replace('.mp4', '_720p.mp4'), base.replace('.mp4', '_1080p.mp4'), base]

def _download(url: str, dest: str) -> None:
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            content_type = r.headers.get('content-type', '')
            if content_type and 'video' not in content_type and ('octet-stream' not in content_type):
                raise RuntimeError(f'Unexpected clip content-type: {content_type}')
            expected = r.headers.get('content-length')
            if expected and int(expected) > MAX_DOWNLOAD_BYTES:
                raise RuntimeError(f'Clip too large: {int(expected) // (1024 * 1024)} MB')
            downloaded = 0
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError(f'Clip exceeded limit: {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB')
                    f.write(chunk)
    except Exception:
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        raise

def _larghezza_target() -> int:
    """Return the target video width; larger downloads are unnecessary."""
    try:
        return max(640, int(os.environ.get('VIDEO_WIDTH', 1920)))
    except (TypeError, ValueError):
        return 1920

def _best_file(video_files: list) -> str:
    """Select the smallest available video resolution covering the final output, avoiding unnecessary 4K downloads."""
    utili = [v for v in video_files if v.get('link')]
    if not utili:
        raise RuntimeError('No downloadable video files found in Pexels response')
    target = _larghezza_target()
    sufficienti = [v for v in utili if v.get('width', 0) >= target]
    if sufficienti:
        scelta = min(sufficienti, key=lambda v: v.get('width', 0))
    else:
        scelta = max(utili, key=lambda v: v.get('width', 0))
    return scelta['link']

def _keyword_to_tags(keyword: str) -> list[str]:
    """Generate tags from individual keyword words and the complete phrase."""
    words = [w.lower() for w in keyword.split() if len(w) > 2]
    return list(dict.fromkeys([keyword.lower()] + words))
_STOPWORD_TAG = {'ai', 'the', 'and', 'for', 'with', 'video', 'footage', 'clip', 'shot', 'scene', 'background', 'abstract', 'modern', 'new', 'tech', 'digital'}

def _match_tag(query_tags: set[str], clip_tags: set[str]) -> bool:
    """Match the full phrase or at least two meaningful words. One shared generic word is insufficient."""
    comuni = query_tags & clip_tags
    if any((' ' in t for t in comuni)):
        return True
    return len(comuni - _STOPWORD_TAG) >= 2

def _find_cached_by_tags(tags: list[str], index: dict) -> str | None:
    """Find a cached clip whose tags match the requested tags."""
    query_tags = {t.lower() for t in tags}
    candidati = []
    for kw, meta in index.items():
        clip_tags = {t.lower() for t in meta.get('tags', [])}
        if not _match_tag(query_tags, clip_tags):
            continue
        path_orig = os.path.join(CACHE_DIR, meta.get('file', ''))
        variants = [path_orig.replace('.mp4', '_720p.mp4'), path_orig.replace('.mp4', '_1080p.mp4'), path_orig]
        for path in variants:
            if os.path.exists(path):
                candidati.append(path)
                break
    if not candidati:
        return None
    scelta = random.choice(candidati)
    _tocca(scelta)
    return scelta

def _fetch_metadata(keyword: str, headers: dict) -> dict | None:
    for size in ('large', 'medium'):
        params = {'query': keyword, 'orientation': 'landscape', 'per_page': 5, 'size': size}
        try:
            r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            videos = r.json().get('videos', [])
            if videos:
                v = videos[0]
                return {'file': os.path.basename(_cache_path(keyword)), 'pexels_id': v.get('id'), 'url': v.get('url'), 'duration': v.get('duration'), 'author': v.get('user', {}).get('name'), 'tags': _keyword_to_tags(keyword)}
        except Exception:
            pass
    return None

def scarica_clip(keyword: str, extra_tags: list[str] | None=None) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(keyword)
    api_key = os.environ.get('PEXELS_API_KEY', '')
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set — run 'tube-assistant onboard' to configure")
    headers = {'Authorization': api_key}
    index = _load_index()
    cached = next((p for p in _cache_variants(keyword) if os.path.exists(p)), None)
    if cached:
        if keyword not in index:
            meta = _fetch_metadata(keyword, headers)
            if meta:
                index[keyword] = meta
                _save_index(index)
        else:
            entry = index[keyword]
            if not entry.get('tags'):
                entry['tags'] = _keyword_to_tags(keyword)
                if extra_tags:
                    entry['tags'] = list(dict.fromkeys(entry['tags'] + [t.lower() for t in extra_tags]))
                _save_index(index)
        _tocca(cached)
        return cached
    all_tags = _keyword_to_tags(keyword) + (extra_tags or [])
    match = _find_cached_by_tags(all_tags, index)
    if match:
        return match
    params = {'query': keyword, 'orientation': 'landscape', 'per_page': 15, 'size': 'large'}
    r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    videos = r.json().get('videos', [])
    if not videos:
        params['size'] = 'medium'
        r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
        r.raise_for_status()
        videos = r.json().get('videos', [])
    if not videos:
        raise RuntimeError(f'No Pexels results for: {keyword}')
    videos = _ordina_per_rilevanza(_filtra_durata(videos), keyword)
    link = _best_file(videos[0]['video_files'])
    _download(link, path)
    tags = _keyword_to_tags(keyword)
    if extra_tags:
        tags = list(dict.fromkeys(tags + [t.lower() for t in extra_tags]))
    index[keyword] = {'file': os.path.basename(path), 'pexels_id': videos[0].get('id'), 'url': videos[0].get('url'), 'duration': videos[0].get('duration'), 'author': videos[0].get('user', {}).get('name'), 'tags': tags}
    _save_index(index)
    return path

def scarica_clips(keyword: str, max_n: int=3, extra_tags: list[str] | None=None, escludi: set[str] | None=None) -> list[str]:
    """Download up to max_n distinct clips per keyword. Exclude paths already in this video to expand the clip pool."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    api_key = os.environ.get('PEXELS_API_KEY', '')
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set — run 'tube-assistant onboard' to configure")
    headers = {'Authorization': api_key}
    index = _load_index()
    escludi = {os.path.abspath(p) for p in escludi or ()}
    videos = []
    for size in ('large', 'medium'):
        params = {'query': keyword, 'orientation': 'landscape', 'per_page': min(PEXELS_PER_PAGE_MAX, max(max_n * 4, 40)), 'size': size}
        try:
            r = requests.get(PEXELS_SEARCH, headers=headers, params=params, timeout=15)
            r.raise_for_status()
            videos = r.json().get('videos', [])
        except Exception:
            videos = []
        if videos:
            break
    if not videos:
        raise RuntimeError(f'No Pexels results for: {keyword}')
    videos = _ordina_per_rilevanza(_filtra_durata(videos), keyword)
    tags = _keyword_to_tags(keyword)
    if extra_tags:
        tags = list(dict.fromkeys(tags + [t.lower() for t in extra_tags]))
    paths = []
    for v in videos:
        if len(paths) >= max_n:
            break
        vid = v.get('id')
        if vid is None:
            continue
        dest = _cache_path_id(vid)
        cached = _existing_variant(dest)
        if cached:
            if os.path.abspath(cached) in escludi:
                continue
            _tocca(cached)
            paths.append(cached)
        else:
            if os.path.abspath(dest) in escludi:
                continue
            try:
                link = _best_file(v['video_files'])
                _download(link, dest)
                paths.append(dest)
            except Exception as e:
                print(f'[asset] clip {vid} skipped: {e}', flush=True)
                continue
        index[f'pex_{vid}'] = {'file': os.path.basename(dest), 'pexels_id': vid, 'url': v.get('url'), 'duration': v.get('duration'), 'author': v.get('user', {}).get('name'), 'tags': tags}
    if paths:
        _save_index(index)
    return paths

def rebuild_index(keywords: list[str]) -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    headers = {'Authorization': os.environ['PEXELS_API_KEY']}
    index = _load_index()
    updated = 0
    for keyword in keywords:
        path = _cache_path(keyword)
        entry = index.get(keyword, {})
        if os.path.exists(path) and keyword not in index:
            meta = _fetch_metadata(keyword, headers)
            if meta:
                index[keyword] = meta
                updated += 1
        elif keyword in index and (not entry.get('tags')):
            index[keyword]['tags'] = _keyword_to_tags(keyword)
            updated += 1
    if updated:
        _save_index(index)
    return {'total': len(index), 'added': updated}

def _stampa(msg: str) -> None:
    """Print safely when the console cannot represent arrows, check marks or other characters."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
        print(msg.encode(enc, errors='replace').decode(enc), flush=True)

def scarica_pool_clips(keywords: list[str], audio_path: str | None=None, log=_stampa) -> dict:
    """Download enough distinct clips to cover all video segments."""
    clip_paths: dict[str, str] = {}
    if not keywords:
        return clip_paths
    try:
        from moduli.montaggio import _media_duration, SEGMENT_DURATION
        target_clips = int(_media_duration(audio_path) / SEGMENT_DURATION) + 1
        durata_clip = int(SEGMENT_DURATION)
    except Exception:
        target_clips = max(len(keywords), 20)
        durata_clip = 5
    seen: set[str] = set()

    def _aggiungi(kw: str, paths: list[str]) -> int:
        nuove = 0
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            clip_paths[f'{kw}#{len(clip_paths)}'] = p
            nuove += 1
        return nuove
    sorgente = 'pexels'
    try:
        from moduli import video_ai
        sorgente = video_ai.sorgente_video()
        if sorgente != 'pexels':
            quante = target_clips if sorgente == 'ai' else min(video_ai.max_clip(), target_clips)
            for path in video_ai.genera_pool(keywords, quante, durata_clip, log=log):
                if path not in seen:
                    seen.add(path)
                    clip_paths[f'ai#{len(clip_paths)}'] = path
    except Exception as e:
        log(f'  → AI generation skipped: {e}')
    if sorgente == 'ai' and clip_paths:
        log(f'  → {len(clip_paths)} AI clips (AI only, no Pexels downloads)')
        return clip_paths
    if sorgente == 'ai':
        log('  → No AI clips produced: falling back to Pexels')
    mancanti_stock = max(0, target_clips - len(clip_paths))
    if mancanti_stock <= 0:
        log(f'  → {len(clip_paths)} distinct clips (all AI generated)')
        return clip_paths
    per_kw = max(1, -(-mancanti_stock // max(1, len(keywords))))
    log(f'  → Servono ~{target_clips} clip distinte → {per_kw} per keyword from Pexels')
    resa: dict[str, int] = {}
    for i, kw in enumerate(keywords):
        log(f'  → [{i + 1}/{len(keywords)}] Cerco: {kw} (x{per_kw})')
        try:
            nuove = _aggiungi(kw, scarica_clips(kw, max_n=per_kw))
            resa[kw] = nuove
            log(f'     ✓ {nuove} clip distinte')
        except Exception as e:
            resa[kw] = 0
            log(f'     ✗ Skipped: {e}')
    produttive = [kw for kw, n in resa.items() if n >= per_kw]
    giro = 0
    while len(clip_paths) < target_clips and produttive and (giro < 3):
        giro += 1
        mancanti = target_clips - len(clip_paths)
        extra = max(1, -(-mancanti // len(produttive)))
        log(f'  → Loading {giro}: missing {mancanti} clip → +{extra} per keyword')
        progresso = 0
        ancora = []
        for kw in produttive:
            if len(clip_paths) >= target_clips:
                ancora.append(kw)
                continue
            try:
                nuove = _aggiungi(kw, scarica_clips(kw, max_n=extra, escludi=set(clip_paths.values())))
            except Exception as e:
                log(f'     ✗ {kw}: {e}')
                continue
            resa[kw] += nuove
            progresso += nuove
            if nuove:
                ancora.append(kw)
        if not progresso:
            break
        produttive = ancora
    log(f'  → {len(clip_paths)} distinct clips downloaded (target {target_clips})')
    return clip_paths
