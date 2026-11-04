"""Disk maintenance: free-space checks and cache cleanup."""
import os
import glob
import shutil
import time
CACHE_DIR = os.environ.get('CACHE_DIR', 'cache/pexels')

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
MIN_FREE_DISK_GB = _env_float('MIN_FREE_DISK_GB', 5.0)
MAX_CACHE_MB = _env_float('MAX_CACHE_MB', 2000.0)
AI_CACHE_DIR = os.environ.get('VIDEO_AI_CACHE_DIR', 'cache/ai_video')
MAX_AI_CACHE_MB = _env_float('MAX_AI_CACHE_MB', 3000.0)

def spazio_libero_gb(path: str='.') -> float:
    """Return free space in gigabytes on the filesystem containing path."""
    try:
        target = path if os.path.exists(path) else '.'
        free = shutil.disk_usage(target).free
        return free / 1024 ** 3
    except OSError:
        return float('inf')

def assicura_spazio(min_gb: float=None, work_dir: str='output', protetti: set=None) -> None:
    """If free space is below the threshold, prune caches first; raise an error if space is still insufficient."""
    min_gb = MIN_FREE_DISK_GB if min_gb is None else min_gb
    libero = spazio_libero_gb(work_dir)
    if libero >= min_gb:
        return
    liberati = pulisci_cache(max_mb=0, protetti=protetti)
    libero = spazio_libero_gb(work_dir)
    if libero >= min_gb:
        return
    raise RuntimeError(f'Insufficient disk space: {libero:.1f} GB liberi, ne servono almeno {min_gb:.1f} GB for editing. Cleared {liberati:.0f} MB of cache, but more space is needed. Free disk space and run /run again.')

def _cache_files(cartella: str=None) -> list[str]:
    cartella = CACHE_DIR if cartella is None else cartella
    if not os.path.isdir(cartella):
        return []
    return [p for p in glob.glob(os.path.join(cartella, '*.mp4')) if os.path.isfile(p)]

def cache_size_mb() -> float:
    return sum((os.path.getsize(p) for p in _cache_files())) / 1024 ** 2

def _pota(cartella: str, max_mb: float, protetti_abs: set) -> float:
    """Prune a clip folder to max_mb using modification-time LRU; return freed megabytes."""
    files = _cache_files(cartella)
    if not files:
        return 0.0
    total = sum((os.path.getsize(p) for p in files))
    limit = max_mb * 1024 ** 2
    if total <= limit:
        return 0.0
    files.sort(key=lambda p: os.path.getmtime(p))
    liberati = 0
    for p in files:
        if total <= limit:
            break
        if os.path.abspath(p) in protetti_abs:
            continue
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            total -= sz
            liberati += sz
        except OSError:
            continue
    return liberati / 1024 ** 2

def pulisci_cache(max_mb: float=None, protetti: set=None) -> float:
    """Keep each clip cache within its size limit by removing the oldest files."""
    protetti_abs = {os.path.abspath(p) for p in protetti or ()}
    tetto_pexels = MAX_CACHE_MB if max_mb is None else max_mb
    tetto_ai = MAX_AI_CACHE_MB if max_mb is None else max_mb
    return _pota(CACHE_DIR, tetto_pexels, protetti_abs) + _pota(AI_CACHE_DIR, tetto_ai, protetti_abs)

def pulisci_temp_render(work_dir: str='output') -> int:
    """Remove orphaned render_* temporary directories left by interrupted renders."""
    rimosse = 0
    if not os.path.isdir(work_dir):
        return 0
    for name in os.listdir(work_dir):
        if name.startswith('render_'):
            full = os.path.join(work_dir, name)
            try:
                if os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
                else:
                    os.remove(full)
                rimosse += 1
            except OSError:
                continue
    return rimosse
