"""Resolve and check the local media tools once per configuration."""
from functools import lru_cache
import os
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, SubprocessError, run


@lru_cache
def _find(tool, override, search_path):
    executable = which(os.path.expanduser(override) if override else tool, path=search_path)
    if executable is None:
        raise RuntimeError(f'{tool} is missing. Install it or set {tool.upper()}_PATH.')
    executable = str(Path(executable).absolute())
    try:
        run([executable, '-version'], stdout=DEVNULL, stderr=DEVNULL, check=True, timeout=5)
    except (OSError, SubprocessError) as exc:
        raise RuntimeError(f'Cannot run {tool} at {executable}') from exc
    return executable


def ffmpeg_path():
    return _find('ffmpeg', os.getenv('FFMPEG_PATH'), os.getenv('PATH', os.defpath))


def ffprobe_path():
    search = os.pathsep.join((str(Path(ffmpeg_path()).parent), os.getenv('PATH', os.defpath)))
    return _find('ffprobe', os.getenv('FFPROBE_PATH'), search)
