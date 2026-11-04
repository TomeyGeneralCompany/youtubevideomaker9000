"""Persistent video style preferences."""
import html
import json
import os
import re
PREF_FILE = 'video-preferences.json'
DEFAULT_PREF = {'pacing': 'medium', 'voice_tone': 'confident', 'language': 'english', 'clip_style': 'cinematic', 'thumbnail_style': 'cinematic dramatic lighting, dark moody', 'preferred_topics': ['AI', 'technology', 'future tech'], 'excluded_topics': [], 'target_duration_minutes': 8, 'music_volume': 0.1, 'notes': '', 'thumbnail_show_text': True, 'thumbnail_text_color': '255,255,255', 'thumbnail_text_position': 'bottom', 'thumbnail_text_scale': 1.0, 'thumbnail_font_size': '', 'tts_voice': ''}

def carica() -> dict:
    if os.path.exists(PREF_FILE):
        try:
            with open(PREF_FILE, encoding='utf-8') as f:
                data = json.load(f)
            return {**DEFAULT_PREF, **data}
        except Exception:
            pass
    return DEFAULT_PREF.copy()

def salva(pref: dict) -> None:
    with open(PREF_FILE, 'w', encoding='utf-8') as f:
        json.dump(pref, f, indent=2, ensure_ascii=False)

def _lista_da_testo(valore: str) -> list[str]:
    valore = re.sub('\\s+(?:e|and)\\s+', ',', valore, flags=re.IGNORECASE)
    return [v.strip(' .;:-"\'') for v in valore.split(',') if v.strip(' .;:-"\'')]

def _converti_valore(chiave: str, valore):
    default_val = DEFAULT_PREF[chiave]
    if isinstance(default_val, bool):
        if isinstance(valore, bool):
            return valore
        return str(valore).strip().lower() in ('true', '1', 'si', 'yes', 'yes', 'vero')
    if isinstance(default_val, list):
        if isinstance(valore, list):
            return [str(v).strip() for v in valore if str(v).strip()]
        return _lista_da_testo(str(valore))
    if isinstance(default_val, int):
        match = re.search('\\d+', str(valore))
        if not match:
            raise ValueError(f'Invalid value for {chiave}')
        return int(match.group(0))
    if isinstance(default_val, float):
        raw = str(valore).replace(',', '.')
        match = re.search('\\d+(?:\\.\\d+)?', raw)
        if not match:
            raise ValueError(f'Invalid value for {chiave}')
        return float(match.group(0))
    return str(valore).strip().strip('"').strip("'")

def aggiorna(chiave: str, valore) -> dict:
    pref = carica()
    pref[chiave] = _converti_valore(chiave, valore)
    salva(pref)
    return pref

def formato_html() -> str:
    pref = carica()
    lines = ['⚙️ <b>Current video preferences:</b>\n']
    for k, v in pref.items():
        val = ', '.join(v) if isinstance(v, list) else str(v)
        lines.append(f"<b>{html.escape(k)}</b>: {html.escape(val or '-')}")
    lines.append('\nYou can use natural language, for example:')
    lines.append('<code>metti pacing fast</code>')
    lines.append('<code>avoid crypto and web3</code>')
    lines.append('<code>thumbnail with vivid colors and an energetic style</code>')
    return '\n'.join(lines)

def come_contesto() -> str:
    pref = carica()
    return f"[CHANNEL USER PREFERENCES]\n- Pacing: {pref['pacing']}\n- Voice tone: {pref['voice_tone']}\n- Language: {pref['language']}\n- Clip style: {pref['clip_style']}\n- Thumbnail style: {pref['thumbnail_style']}\n- Thumbnail text: {('yes' if pref.get('thumbnail_show_text', True) else 'no')}\n- Thumbnail text color: {pref.get('thumbnail_text_color', '255,255,255')}\n- Thumbnail text position: {pref.get('thumbnail_text_position', 'bottom')}\n- Thumbnail text scale: {pref.get('thumbnail_text_scale', 1.0)} (0.3-1.0)\n- TTS voice: {pref.get('tts_voice', '')}\n- Preferred topics: {', '.join(pref['preferred_topics'])}\n- Excluded topics: {', '.join(pref['excluded_topics']) or 'none'}\n- Target duration: {pref['target_duration_minutes']} minutes\n- Note: {pref['notes'] or 'none'}"
LEGACY_KEYS = {'ritmo': 'pacing', 'tono_voce': 'voice_tone', 'lingua': 'language', 'stile_clip': 'clip_style', 'stile_thumbnail': 'thumbnail_style', 'argomenti_preferiti': 'preferred_topics', 'argomenti_evitare': 'excluded_topics', 'durata_target_minuti': 'target_duration_minutes', 'musica_volume': 'music_volume', 'note_libere': 'notes', 'thumbnail_testo_mostra': 'thumbnail_show_text', 'thumbnail_testo_colore': 'thumbnail_text_color', 'thumbnail_testo_posizione': 'thumbnail_text_position', 'thumbnail_testo_scala': 'thumbnail_text_scale', 'tts_voce': 'tts_voice', 'ibrido': 'hybrid', 'lento': 'slow', 'medio': 'medium', 'veloce': 'fast', 'alto': 'top', 'basso': 'bottom'}
_original_load = carica

def carica():
    values = _original_load()
    for old, new in LEGACY_KEYS.items():
        if old in values:
            values[new] = values.pop(old)
    for key in ('pacing', 'thumbnail_text_position'):
        values[key] = LEGACY_KEYS.get(values.get(key), values.get(key))
    return values

def aggiorna_da_testo(text):
    """Apply explicit English preference requests; leave ambiguous requests to the AI."""
    import re
    changes = {}
    request = text.strip()
    if request.endswith('?') and (not re.match('(?i)^(?:please |can you |could you )?(?:set|change|make|use|add|remove|hide|show)', request)):
        return changes

    def apply(key, value):
        aggiorna(key, value)
        changes[key] = value
    for key in DEFAULT_PREF:
        match = re.search('(?i)\\b' + re.escape(key) + '\\s*[:=]\\s*(.+)', request)
        if match:
            apply(key, match.group(1).strip())
            return changes
    low = request.lower()
    pacing = re.search('\\b(?:pacing|pace|speed)\\s*(?:to |is |: |=?\\s*)(slow|medium|fast)\\b', low)
    if pacing:
        apply('pacing', pacing.group(1))
    tone = re.search('\\b(?:voice tone|tone)\\s*(?:to |: |=?\\s*)(confident|casual|dramatic|educational)\\b', low)
    if tone:
        apply('voice_tone', tone.group(1))
    language = re.search('\\b(?:language|speak)\\s*(?:to |in |: |=?\\s*)(english|italian)\\b', low)
    if language:
        apply('language', language.group(1))
    duration = re.search('\\b(\\d+(?:\\.\\d+)?)\\s*(?:minute|min)\\b', low)
    if duration:
        apply('target_duration_minutes', duration.group(1))
    avoid = re.search('\\b(?:avoid|exclude|do not cover)\\s+(.+)', request, re.I)
    if avoid:
        apply('excluded_topics', avoid.group(1))
    prefer = re.search('\\b(?:preferred topics|focus on|prefer topics)\\s*[:=]?\\s+(.+)', request, re.I)
    if prefer:
        apply('preferred_topics', prefer.group(1))
    if re.search('\\b(?:hide|remove|no)\\s+(?:thumbnail )?text\\b', low):
        apply('thumbnail_show_text', False)
    elif re.search('\\b(?:show|add)\\s+(?:thumbnail )?text\\b', low):
        apply('thumbnail_show_text', True)
    position = re.search('\\b(?:text|caption).*\\b(top|bottom)\\b', low)
    if position:
        apply('thumbnail_text_position', position.group(1))
    color = re.search('\\b(?:text|caption).*?\\b(red|blue|green|yellow|white|black|orange|purple|gold|teal)\\b', low)
    if color:
        apply('thumbnail_text_color', color.group(1))
    if re.search('\\b(?:bigger|larger)\\b.*\\btext\\b|\\btext\\b.*\\b(?:bigger|larger)\\b', low):
        apply('thumbnail_text_scale', 1.0)
    if re.search('\\b(?:smaller)\\b.*\\btext\\b|\\btext\\b.*\\bsmaller\\b', low):
        apply('thumbnail_text_scale', 0.65)
    return changes
load_preferences = carica
save_preferences = salva
update_preference = aggiorna
update_from_text = aggiorna_da_testo
format_preferences_html = formato_html
preferences_context = come_contesto
