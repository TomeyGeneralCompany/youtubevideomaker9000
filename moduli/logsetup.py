"""Persist stdout and stderr to a rotating logs/agent.log while retaining console output. Also support launchers without a console."""
import io
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
LOG_DIR = 'logs'
LOG_FILE = os.path.join(LOG_DIR, 'agent.log')
MAX_BYTES = 2000000
BACKUP_COUNT = 3
_installato = False

class _Tee(io.TextIOBase):

    def __init__(self, originale, logger: logging.Logger, level: int):
        self._orig = originale
        self._logger = logger
        self._level = level
        self._buf = ''

    def write(self, s: str) -> int:
        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass
        self._buf += s
        while '\n' in self._buf:
            riga, self._buf = self._buf.split('\n', 1)
            if riga.strip():
                try:
                    self._logger.log(self._level, riga)
                except Exception:
                    pass
        return len(s)

    def flush(self) -> None:
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

    @property
    def encoding(self) -> str:
        return getattr(self._orig, 'encoding', None) or 'utf-8'

    def isatty(self) -> bool:
        try:
            return bool(self._orig and self._orig.isatty())
        except Exception:
            return False

def forza_utf8() -> None:
    """Set stdout and stderr to UTF-8 with replacement so unsupported characters cannot abort production."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

def setup() -> None:
    """Install the log tee once; repeated calls are safe."""
    global _installato
    if _installato:
        return
    forza_utf8()
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        logger = logging.getLogger('tube_assistant')
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        sys.stdout = _Tee(sys.stdout, logger, logging.INFO)
        sys.stderr = _Tee(sys.stderr, logger, logging.ERROR)
        _installato = True
    except OSError:
        pass
