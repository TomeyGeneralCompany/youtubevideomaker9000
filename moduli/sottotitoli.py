"""Generate SRT subtitles from narrated text."""
import re
MAX_PAROLE_BLOCCO = 12

def _blocchi(script: str) -> list[str]:
    """Split narration into readable sentence blocks of at most twelve words."""
    testo = re.sub('\\s+', ' ', script or '').strip()
    if not testo:
        return []
    frasi = [s.strip() for s in re.split('(?<=[.!?])\\s+', testo) if s.strip()]
    blocchi = []
    for frase in frasi:
        parole = frase.split()
        for i in range(0, len(parole), MAX_PAROLE_BLOCCO):
            blocchi.append(' '.join(parole[i:i + MAX_PAROLE_BLOCCO]))
    return blocchi

def _timestamp(secondi: float) -> str:
    ms = max(0, int(round(secondi * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def genera_srt(script: str, durata_audio: float, output_path: str) -> str | None:
    """Write an SRT file and return its path, or None for empty input."""
    blocchi = _blocchi(script)
    if not blocchi or durata_audio <= 0:
        return None
    tot_parole = sum((len(b.split()) for b in blocchi))
    righe = []
    t = 0.0
    for i, blocco in enumerate(blocchi, 1):
        durata = durata_audio * len(blocco.split()) / tot_parole
        fine = min(t + durata, durata_audio)
        righe.append(f'{i}\n{_timestamp(t)} --> {_timestamp(fine)}\n{blocco}\n')
        t = fine
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(righe))
    return output_path
