import json
import os
from datetime import datetime, timezone
MEMORY_FILE = 'memoria_lungo_termine.json'

def _load() -> list[dict]:
    if os.path.exists(MEMORY_FILE):
        for enc in ('utf-8', 'cp1252', 'latin-1'):
            try:
                with open(MEMORY_FILE, encoding=enc) as f:
                    return json.load(f)
            except (UnicodeDecodeError, ValueError):
                continue
    return []

def _save(memories: list[dict]) -> None:
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(memories, f, indent=2, ensure_ascii=False)

def aggiungi(testo: str) -> None:
    memories = _load()
    memories.append({'text': testo.strip(), 'data': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})
    _save(memories)

def rimuovi(indice: int) -> str | None:
    memories = _load()
    if 0 <= indice < len(memories):
        rimossa = memories.pop(indice)
        _save(memories)
        return rimossa['text']
    return None

def svuota() -> None:
    _save([])

def lista() -> list[dict]:
    return _load()

def come_contesto() -> str:
    memories = _load()
    if not memories:
        return ''
    righe = '\n'.join((f"- {m['text']} [{m['data']}]" for m in memories))
    return f'[LONG-TERM MEMORY]\n{righe}'
