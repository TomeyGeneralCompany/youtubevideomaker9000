import json
import os
import random
import re
from datetime import datetime
from moduli.ai_client import chat_ollama
_ANGLES = ['a surprising real-world consequence', 'a contrarian take most people get wrong', 'a hidden risk nobody talks about', 'a behind-the-scenes look at how it actually works', 'a head-to-head comparison', 'a beginner-friendly explainer of a complex idea', 'a near-future prediction with concrete stakes', 'a myth-busting deep dive', 'an underrated tool or technique', 'a story of a spectacular failure and its lesson', 'a practical how-to people can use today', "a 'what if' thought experiment"]
_FORMATS = ['listicle (top N)', 'single big idea explained', 'case study', 'tutorial / walkthrough', 'news reaction / analysis', 'myth vs reality', 'timeline / evolution story', 'versus comparison']
_SUBTHEMES = ['Donald Trump speeches and memorable public appearances', 'MAGA rally traditions and crowd spectacle', 'the history and evolution of the MAGA movement', 'Trump presidential ceremonies and official events', 'MAGA merchandise, symbols and visual culture', 'Trump supporters and their personal stories', 'religious symbolism and providential beliefs among Trump supporters', 'Trump-related patriotic music and entertainment', "historic moments in Trump's political career", 'Trump memes, humor and internet fan culture']
TOPIC_PROMPT = "You are a YouTube content strategist covering Donald Trump and MAGA fan culture.\n\nToday's date: {current_date}\nCurrent strategy guidance: {strategy_notes}\nTopic focus: {topic_focus}\n{trending_block}\nFor THIS video, lean into:\n- Sub-theme to explore: {subtheme}\n- Creative angle: {angle}\n- Content format: {fmt}\n\nGenerate ONE topic about Donald Trump, MAGA history, speeches, rallies, or supporter culture.\nBase your suggestion on what is relevant and trending as of {current_date}.\nUse the trending news above as inspiration for a timely, high-interest angle — not a copy.\nMake it clearly DIFFERENT from the recent topics below — new subject, new framing.\nAvoid repeating these recent topics: {recent_topics}\nReply with ONLY the topic as a short phrase (3-7 words). No explanation, no punctuation."
CONTENT_PROMPT = 'You are a YouTube scriptwriter covering Donald Trump and MAGA fan culture.\nToday\'s date: {current_date}\n\nTHE SUBJECT OF THIS VIDEO IS FIXED — it is: {topic}\nEverything you write (title, script, description, tags, keywords) must be about\nthat exact subject. This is not negotiable.\n\nStrategy guidance — this shapes HOW you write, never WHAT the video is about.\nAdapt the title formula to the subject above; if the formula does not fit the\nsubject, keep the subject and drop the formula.\n- Title style: {title_style}\n- Tone: {tone}\n- Hook strength: {hook_strength}\n- Notes: {strategy_notes}\n\nTarget duration: {target_minutes} minutes = ~{target_words} words\nLanguage: write title, description, tags and script entirely in {language}.\n\nReply ONLY with valid JSON, exact structure:\n{{\n  "title": "Compelling title, max 70 chars",\n  "mood": "ONE word matching the video\'s emotional tone: epic | chill | mysterious | upbeat | tense",\n  "thumbnail_phrase": "2-3 words MAX, ALL CAPS, bold visual hook for the thumbnail — never more than 3 words, never cut off",\n  "thumbnail_font_size": "ONE letter: A (very large, best for 2 words), B (large, 2 words), C (medium, 2-3 words, default), D (smaller, 3 words)",\n  "description": "SEO-optimized description, 200-300 words, include keywords naturally",\n  "tags": ["tag1", "tag2", "tag3"],\n  "script": "Full narration. Engaging, clear, conversational. Exactly {target_words} words. No headers or sections, flowing prose.",\n  "video_keywords": [\n    "American flags at political rally",\n    "presidential podium and flags",\n    "patriotic crowd celebration"\n  ],\n  "thumbnail_description": "Ultra-detailed image generation prompt for FLUX.1 diffusion model. Must be ONE paragraph, 80-120 words. Describe: exact scene composition, foreground subject with precise visual details (clothing, pose, expression, materials), background environment (architecture, lighting, atmosphere, depth), color palette (specific hues, contrast, saturation), lighting setup (direction, quality, color temperature, shadows), cinematic style, camera angle, lens feel. Professional YouTube thumbnail aesthetic, bold visual impact, 16:9 landscape orientation. NO text, logos, watermarks, or words of any kind — pure visual only. Example depth: \'Cinematic wide-angle photograph of a large American political rally, hundreds of waving American flags, dramatic golden-hour lighting, vivid red white and blue color palette, energetic crowd, monumental stage architecture, strong foreground composition, sharp details, atmospheric depth, professional editorial photography.\'"\n}}\n\nRules:\n- title: follow the title_style guidance above\n- mood: exactly one of epic, chill, mysterious, upbeat, tense — drives background music and thumbnail style\n- thumbnail_phrase: EXACTLY 2-3 words, ALL CAPS, bold hook — never more than 3 words\n- thumbnail_font_size: A if 2 short words, B if 2 longer words, C if 3 words (default), D if 3 long words\n- tags: 12-15 relevant tags\n- script: exactly {target_words} words, engaging pace, no bullet points\n- video_keywords: 12-18 unique English phrases describing stock video scenes (2-4 words each, concrete and visual)\n- thumbnail_description: ultra-detailed FLUX.1 prompt as described above, always present\n'
PAROLE_AL_MINUTO_DEFAULT = 150

def _parole_al_minuto() -> float:
    try:
        return max(60.0, float(os.environ.get('PAROLE_AL_MINUTO', PAROLE_AL_MINUTO_DEFAULT)))
    except (TypeError, ValueError):
        return PAROLE_AL_MINUTO_DEFAULT
SOGLIA_SCRIPT_BUONA = 0.8
SOGLIA_SCRIPT_MINIMA = 0.5
TENTATIVI_CONTENUTO = 3
MIN_OCCORRENZE_TEMA = 3
MAX_TOKEN_TOPIC = 400
MAX_PAROLE_TOPIC = 14
_SPIE_RAGIONAMENTO = ('we need to', 'the user', 'let me', 'i should', 'i need to', 'okay,', 'reply with', 'no punctuation', 'no explanation', 'as an ai')
_PAROLE_VUOTE = {'the', 'a', 'an', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'is', 'are', 'how', 'why', 'what', 'with', 'from', 'that', 'this', 'it', 'its', 'ai', 'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'di', 'del', 'della', 'da', 'per', 'con', 'su', 'che', 'e', 'o', 'come', 'perche', 'perché', 'dai', 'ai', 'agli', 'alle', 'nel', 'sono', 'essere', 'oggi', 'degli', 'dei', 'delle', 'dalla', 'dallo', 'dagli', 'sulla', 'sullo', 'nella', 'nello', 'negli', 'nelle', 'questo', 'questa', 'quello'}

def _parole_chiave(testo: str) -> set:
    """Extract meaningful words for comparing the requested topic with generated content."""
    pezzi = re.split('[^0-9A-Za-zÀ-ÿ]+', (testo or '').lower())
    return {p for p in pezzi if len(p) > 3} - _PAROLE_VUOTE

def _ancore(testo: str) -> set:
    """Find topic anchors that survive translation, such as acronyms, names and numbers."""
    ancore = set()
    for pezzo in re.split('[^0-9A-Za-zÀ-ÿ\\-]+', testo or ''):
        nudo = pezzo.strip('-')
        if len(nudo) < 3:
            continue
        parte_alfabetica = re.sub('[^A-Za-zÀ-ÿ]', '', nudo)
        ha_cifre = any((c.isdigit() for c in nudo))
        e_sigla = parte_alfabetica.isupper() and len(parte_alfabetica) >= 2
        e_nome_proprio = parte_alfabetica[:1].isupper() and (not parte_alfabetica.isupper())
        if ha_cifre or e_sigla or e_nome_proprio:
            ancore.add(parte_alfabetica.lower() or nudo.lower())
    return {a for a in ancore if a and a not in _PAROLE_VUOTE}

def _prompt_senza_strategia(prompt: str) -> str:
    """Replace strategy lines with neutral instructions."""
    neutro = {'- Title style:': '- Title style: clear and descriptive, name the subject explicitly', '- Tone:': '- Tone: confident and informative', '- Hook strength:': '- Hook strength: medium', '- Notes:': '- Notes: ignore any previous formula, write about the fixed subject above'}
    righe = []
    for riga in prompt.splitlines():
        sostituita = next((v for k, v in neutro.items() if riga.startswith(k)), None)
        righe.append(sostituita if sostituita else riga)
    return '\n'.join(righe)

def _contenuto_fuori_tema(topic: str, content: dict) -> bool:
    """Detect content that does not address the requested topic."""
    ancore = _ancore(topic)
    if not ancore:
        return False
    titolo = (content.get('title') or '').lower()
    script = (content.get('script') or '').lower()
    if any((a in titolo for a in ancore)):
        return False
    occorrenze = sum((script.count(a) for a in ancore))
    return occorrenze < MIN_OCCORRENZE_TEMA

def _topic_non_valido(topic: str, recent_norm: set) -> str:
    """Return a rejection reason, or an empty string for a valid topic."""
    t = (topic or '').strip()
    if not t:
        return 'empty'
    if len(t.split()) > MAX_PAROLE_TOPIC:
        return f'{len(t.split())} words; appears to contain model reasoning'
    basso = t.lower()
    if any((s in basso for s in _SPIE_RAGIONAMENTO)):
        return 'contiene frasi di ragionamento'
    if basso in recent_norm:
        return 'recently used'
    return ''

def _parse_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    start = text.find('{')
    if start < 0:
        raise ValueError('No JSON found in model response')
    try:
        data, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as e:
        snippet = text[:500].replace('\n', '\\n')
        if e.pos >= len(text[start:]) - 2:
            raise ValueError(f'Model response truncated (incomplete JSON): the script exceeds the output limit. Reduce target_duration_minutes or increase AI_MAX_TOKENS in .env. Details: {e}') from e
        raise ValueError(f'Invalid JSON from model: {e}; response starts with: {snippet}') from e
    required = {'title', 'description', 'tags', 'script', 'video_keywords'}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Model JSON missing required fields: {', '.join(sorted(missing))}")
    return data

def _fetch_trending() -> str:
    try:
        from moduli.web_search import cerca_notizie
        results = cerca_notizie('AI technology breakthrough news 2026', max_results=5)
        if results:
            return f'\nTRENDING NOW (use as inspiration for a timely topic angle):\n{results}\n'
    except Exception:
        pass
    return ''

def genera_topic(strategy: dict=None, recent_topics: list=None) -> str:
    strategy = strategy or {}
    trending = _fetch_trending()
    angle = random.choice(_ANGLES)
    fmt = random.choice(_FORMATS)
    subtheme = random.choice(_SUBTHEMES)
    print(f'[cervello] Leve creative — tema:{subtheme} | angolo:{angle} | formato:{fmt}', flush=True)
    prompt = TOPIC_PROMPT.format(current_date=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'), strategy_notes=strategy.get('notes', 'Standard approach'), topic_focus=strategy.get('topic_focus', 'Donald Trump, MAGA events, speeches, history, and supporter culture'), recent_topics=', '.join(recent_topics or []) or 'none', trending_block=trending, angle=angle, fmt=fmt, subtheme=subtheme)
    recent_norm = {t.strip().lower() for t in recent_topics or []}

    def _clean(t: str) -> str:
        return t.strip().strip('"“”‘’\' ')

    def _genera(p: str) -> str:
        return _clean(chat_ollama(p, max_tokens=MAX_TOKEN_TOPIC))
    topic = _genera(prompt)
    for _ in range(2):
        motivo = _topic_non_valido(topic, recent_norm)
        if not motivo:
            break
        print(f'[scripting] Topic rejected ({motivo}): {topic[:60]!r} — ritento', flush=True)
        prompt = prompt.replace(angle, random.choice(_ANGLES)).replace(subtheme, random.choice(_SUBTHEMES))
        topic = _genera(prompt)
    if _topic_non_valido(topic, recent_norm):
        raise ValueError(f'No usable topic after 3 attempts: {topic[:120]!r}. The model did not follow the required format. Try another model using OLLAMA_CLOUD_MODEL or OPENROUTER_MODEL in .env.')
    return topic

def _strategia_neutra(strategy: dict) -> dict:
    """Preserve tone and pacing while removing instructions that dictate the subject."""
    neutra = dict(strategy or {})
    neutra['title_style'] = 'clear and descriptive — the title must name the subject of this video explicitly'
    neutra['notes'] = 'Write about the fixed subject above. Ignore any formula or topic pattern learned from previous videos.'
    neutra.pop('topic_focus', None)
    neutra.pop('avoid_patterns', None)
    return neutra
CONTINUA_PROMPT = 'You are continuing the narration script of a YouTube video.\n\nVideo subject: {topic}\nLanguage: {language}\n\nThe script so far ends with these words:\n...{coda}\n\nWrite ONLY the CONTINUATION — about {mancanti} more words — so the finished\nscript reaches roughly {target_words} words ({target_minutes} minutes of\nnarration).\n\nRules:\n- Start exactly where the text above stops. Do not repeat it, do not summarise it.\n- Do not restart the video, do not greet the viewer again.\n- Flowing spoken prose, same voice and tone. No headings, no bullet points,\n  no stage directions, no JSON, no quotes around the text.\n- Add real substance: concrete examples, numbers, causes and consequences,\n  objections and answers, then a proper closing with a call to action.\n- Reply with the continuation text and nothing else.'
_CODA_PAROLE = 90
MAX_CONTINUAZIONI = 2

def _ripulisci_continuazione(testo: str) -> str:
    """Remove anything from a continuation that is not spoken narration."""
    testo = (testo or '').strip()
    testo = re.sub('^```[a-zA-Z]*\\s*|\\s*```$', '', testo).strip()
    righe = []
    for i, riga in enumerate(testo.splitlines()):
        pulita = riga.strip()
        if pulita.startswith('#'):
            continue
        if i == 0 and pulita.endswith(':') and (len(pulita.split()) <= 8):
            continue
        righe.append(pulita)
    return ' '.join((r for r in righe if r)).strip()

def _allunga_script(content: dict, topic: str, target_words: int, soglia: int, language: str, target_minutes) -> dict:
    """Ask the model to continue the script until it reaches the target length."""
    script = (content.get('script') or '').strip()
    if not script:
        return content
    for _ in range(MAX_CONTINUAZIONI):
        parole = len(script.split())
        if parole >= soglia:
            break
        mancanti = max(target_words - parole, 80)
        prompt = CONTINUA_PROMPT.format(topic=topic, language=language, coda=' '.join(script.split()[-_CODA_PAROLE:]), mancanti=mancanti, target_words=target_words, target_minutes=target_minutes)
        try:
            aggiunta = _ripulisci_continuazione(chat_ollama(prompt, max_tokens=min(8192, mancanti * 2 + 600)))
        except Exception as e:
            print(f'[scripting] Continuation failed: {e}', flush=True)
            break
        nuove = len(aggiunta.split())
        if aggiunta.lstrip().startswith('{') or '"script"' in aggiunta:
            print('[scripting] Continuation discarded: model returned JSON instead of prose', flush=True)
            break
        if nuove < 40:
            print(f'[cervello] Continuazione inutilizzabile ({nuove} words)', flush=True)
            break
        script = f'{script} {aggiunta}'.strip()
        print(f'[scripting] Script extended: +{nuove} words -> {len(script.split())} (soglia {soglia})', flush=True)
    esteso = dict(content)
    esteso['script'] = script
    return esteso
PAUL_REVERE_EDITORIAL = '\nCHANNEL: \nIDENTITY: MAXIMALIST MAGA FAN-CULTURE ENTERTAINMENT.\n\nThis is not a conventional political news channel.\n\nEvery video centers on Donald Trump, MAGA culture, or the history\nand symbolism of the movement.\n\nPRESENTATION:\n- Grand, theatrical, energetic, and unapologetically extravagant.\n- Americana, presidential pageantry, flags, eagles, and rally imagery.\n- Larger-than-life storytelling and enthusiastic fan-culture language.\n- No detached television-news anchor personality.\n- No generic technology or unrelated current-events videos.\n\nSUBJECTS:\n- Memorable Trump speeches and public appearances.\n- Rally spectacle, supporter traditions, and MAGA iconography.\n- Trump-related historical moments and archival footage.\n- Patriotic music, humor, memes, and fan celebrations.\n- Religious imagery and providential interpretations expressed\n  by Trump supporters.\n- Major developments involving Trump and the MAGA movement.\n\nSTYLE:\nMake the entertainment spectacular, colorful, and memorable.\nUse cinematic narration and dramatic pacing.\nDistinguish factual events from opinions and religious beliefs.\nDo not invent quotations, events, or evidence.\n'
_ORIGINAL_TOPIC_PROMPT = TOPIC_PROMPT
_ORIGINAL_CONTENT_PROMPT = CONTENT_PROMPT
TOPIC_PROMPT = PAUL_REVERE_EDITORIAL + '\\n\\nGenerate a topic consistent with this channel.\\n\\n' + _ORIGINAL_TOPIC_PROMPT
CONTENT_PROMPT = PAUL_REVERE_EDITORIAL + '\\n\\nWrite the video content consistent with this channel.\\n\\n' + _ORIGINAL_CONTENT_PROMPT

def genera_contenuto(topic: str, strategy: dict=None, topic_esplicito: bool=False) -> dict:
    strategy = strategy or {}
    if topic_esplicito:
        strategy = _strategia_neutra(strategy)
    try:
        from moduli.preferenze import carica
        pref = carica()
    except Exception:
        pref = {}
    target_minutes = pref.get('target_duration_minutes', 8)
    language = pref.get('language', 'english') or 'english'
    target_words = int(target_minutes * _parole_al_minuto())
    prompt = CONTENT_PROMPT.format(current_date=datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'), topic=topic, title_style=strategy.get('title_style', 'curiosity-driven'), tone=strategy.get('tone', 'confident and informative'), hook_strength=strategy.get('hook_strength', 'medium'), strategy_notes=strategy.get('notes', 'Standard approach'), target_minutes=target_minutes, target_words=target_words, language=language)
    soglia_buona = max(150, int(target_words * SOGLIA_SCRIPT_BUONA))
    soglia_minima = max(120, int(target_words * SOGLIA_SCRIPT_MINIMA))
    migliore = None
    last_err = None
    correzione = ''
    for attempt in range(TENTATIVI_CONTENUTO):
        try:
            content = _parse_json(chat_ollama(prompt + correzione, max_tokens=8192))
            if _contenuto_fuori_tema(topic, content):
                prompt = _prompt_senza_strategia(prompt)
                raise ValueError(f"Content does not address the requested topic: title {content.get('title', '')!r} for topic {topic!r}")
            words = len(content.get('script', '').split())
            if words < soglia_buona:
                content = _allunga_script(content, topic, target_words, soglia_buona, language, target_minutes)
                words = len(content.get('script', '').split())
            if words >= soglia_buona:
                return content
            if migliore is None or words > len(migliore.get('script', '').split()):
                migliore = content
            mancanti = max(soglia_buona - words, 0)
            correzione = f'\n\nRETRY — YOUR PREVIOUS ATTEMPT FAILED.\nThe "script" field contained only {words} words. That is far too short for a {target_minutes}-minute video.\nThis attempt MUST contain AT LEAST {soglia_buona} words in "script" (about {mancanti} words more than last time), ideally {target_words}.\nDo not summarise. Expand with concrete detail: real examples, numbers, causes, consequences, objections and answers, a longer opening hook and a proper closing. Keep it flowing prose, same topic, same JSON structure.'
            last_err = ValueError(f'Script too short: {words} words instead of approximately {target_words} for a video lasting {target_minutes} minutes')
            print(f'[cervello] {last_err} (attempt {attempt + 1}/{TENTATIVI_CONTENUTO})', flush=True)
        except ValueError as e:
            last_err = e
            print(f'[scripting] Invalid content (attempt {attempt + 1}/{TENTATIVI_CONTENUTO}): {e}', flush=True)
    if migliore is not None:
        parole = len(migliore.get('script', '').split())
        if parole >= soglia_minima:
            print(f'[scripting] No attempt reached {soglia_buona} words: using the longest result ({parole}, ~{parole / _parole_al_minuto():.1f} min invece di {target_minutes})', flush=True)
            return migliore
    raise last_err
