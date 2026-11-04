"""
Telegram bot — listens for user commands and topic suggestions.
Runs in a background thread alongside the agent daemon.
"""
import os
import json
import asyncio
import threading
import requests
import html
import uuid
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
MAX_HISTORY = 20
PENDING_ACTION_TTL_SECONDS = 3600

def _h(value) -> str:
    return html.escape(str(value), quote=True)

def _authorized_chat_ids() -> set[str]:
    raw = ','.join((value for value in (os.environ.get('TELEGRAM_CHAT_ID', ''), os.environ.get('TELEGRAM_ALLOWED_CHAT_IDS', '')) if value))
    return {item.strip() for item in raw.split(',') if item.strip()}

def _is_authorized(update: Update) -> bool:
    allowed = _authorized_chat_ids()
    if not allowed:
        return False
    chat = update.effective_chat
    return bool(chat and str(chat.id) in allowed)

async def _deny_unauthorized(update: Update) -> None:
    chat = update.effective_chat
    chat_id = getattr(chat, 'id', None)
    print(f'[Telegram] Unauthorized chat blocked: {chat_id}', flush=True)
    if update.message:
        await update.message.reply_text(f'Unauthorized access.\n\nYour chat ID is: {chat_id}\nTo authorize this chat, set in .env:\nTELEGRAM_CHAT_ID={chat_id}\nthen restart the agent.')

def _authorized(handler):

    async def _wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            await _deny_unauthorized(update)
            return
        return await handler(update, ctx)
    return _wrapped

def _pending_actions(state: dict) -> list[dict]:
    now = datetime.now(timezone.utc).timestamp()
    pending = []
    for action in state.get('pending_actions', []):
        try:
            created = float(action.get('created_at', 0))
        except (TypeError, ValueError):
            created = 0
        if now - created <= PENDING_ACTION_TTL_SECONDS:
            pending.append(action)
    state['pending_actions'] = pending
    return pending

def _queue_pending_action(state: dict, action_type: str, payload: str, label: str) -> str:
    pending = _pending_actions(state)
    action_id = uuid.uuid4().hex[:8]
    pending.append({'id': action_id, 'type': action_type, 'payload': payload, 'label': label, 'created_at': datetime.now(timezone.utc).timestamp()})
    state['pending_actions'] = pending
    return f'Confirmation required: <b>{_h(label)}</b>\nID: <code>{action_id}</code>\nUse <code>/confirm {action_id}</code> within 1 hour, or <code>/cancel {action_id}</code>.'
_AGENT_LANGUAGE = 'English'
SYSTEM_PROMPT = f"""You are the virtual employee of a YouTube channel. Your boss talks to you via Telegram.\nAlways reply in {_AGENT_LANGUAGE}. This is mandatory — never switch language unless the user explicitly asks you to.\nYou EXECUTE what they ask — you don't explain why you can't do it, you just do it.\n\nWHAT YOU CAN DO (do it directly without asking for confirmation):\n- Develop topics: write title, hook, structure, full script\n- Plan videos: propose and add topics to the queue using the tag [ADD_TOPIC: text]\n- Rewrite/improve scripts, titles, descriptions, tags\n- Give YouTube strategy advice based on data\n- Answer any question about the channel, AI, content creation\n\nAUTOMATIC PIPELINE (every day at the configured time):\n1. Reads YouTube analytics → adapts strategy\n2. Generates topic+script via AI → audio with Edge TTS\n3. Downloads Pexels clips → edits video with MoviePy → generates thumbnail\n4. Uploads to YouTube scheduled at the set time\n\nCHANNEL MANAGEMENT VIA COMMANDS:\n/run /publishnow /skip /setpublish /status /recap /upcoming\n/queue /topic /deltopic\n/channel /setdesc /video /playlist /newplaylist /comments\n\nSTANDALONE GENERATION ACTIONS (execute immediately, no pipeline, no queue):\n[GENERATE_THUMBNAIL: title] → generate thumbnail image and send it. Use for: "generate/create/show me a thumbnail", "test thumbnail". ONLY this tag — no [PUBLISH_NOW], no [ADD_TOPIC].\n[GENERATE_AUDIO: text] → generate TTS audio from text and send it as audio file. Use for: "generate audio", "let me hear the voice", "test TTS", "how this text sounds". ONLY this tag.\n[GENERATE_SCRIPT: topic] → generate full video script (title + script + description + tags) and send as text. Use for: "write a script", "generate a script about X", "show me the script". Does NOT start pipeline. ONLY this tag.\n[SEND_VIDEO] → send the last produced video file. Use for: "send me the video", "send the video", "show the video". No payload.\n\nQUEUE & PIPELINE ACTIONS (require explicit intent to produce/publish):\n[ADD_TOPIC: title] → add topic to end of queue\n[PRIORITIZE_TOPIC: title] → add topic to head of queue (next video)\n[PUBLISH_NOW: title] → add to head of queue AND start pipeline immediately (requires confirmation)\n\nCHANNEL API ACTIONS (execute directly, no confirmation needed):\n[UPDATE_DESCRIPTION: description text] → update channel description via API\n[UPDATE_KEYWORDS: keyword1, keyword2] → update channel keywords via API\n[RENAME_CHANNEL: new name] → change channel name via API (requires confirmation — irreversible)\n[REMOVE_TOPIC: N] → remove topic number N from the queue (1 = first)\n\nMEMORY & PREFERENCES:\n[REMEMBER: fact] → save to long-term memory\n[FORGET: text] → remove from memory\n[SETPREF: key=value] → update video preference. Available keys: pacing (slow/medium/fast), voice_tone (confident/casual/dramatic/educational), language (english/italian), clip_style (cinematic/fast cuts/minimal/documentary), thumbnail_style (free text), preferred_topics (comma-separated list), excluded_topics (comma-separated list), target_duration_minutes (number), music_volume (0.0-1.0), notes (free text), thumbnail_show_text (true/false), thumbnail_text_color (color name or R,G,B), thumbnail_text_position (top/bottom), thumbnail_text_scale (0.3-1.0), thumbnail_font_size (A/B/C/D — A largest, empty = auto), tts_voice (Edge TTS voice name). ALWAYS use this tag when the user expresses a preference.\nExamples: "Italian voice" → [SETPREF: tts_voice=it-IT-DiegoNeural] | "female voice" → [SETPREF: tts_voice=en-US-AriaNeural] | "British voice" → [SETPREF: tts_voice=en-GB-SoniaNeural] | "five-minute video" → [SETPREF: target_duration_minutes=5]\n\nPUBLISHED VIDEO EDITING (requires confirmation — affects live content):\n[VIDEO_TITLE: video_id | new title] → change title of published video\n[VIDEO_DESC: video_id | new description] → change description of published video\n[VIDEO_TAGS: video_id | tag1, tag2, tag3] → change tags of published video\n[VIDEO_THUMB: video_id] → re-upload thumbnail on published video (uses output/thumbnail.jpg)\n\nPIPELINE CONTROL:\n[RESTART_EDITING] → clear checkpoint and restart pipeline (requires confirmation)\n[STOP_PIPELINE] → stop pipeline in progress (requires confirmation)\n\nCRITICAL RULE ON SEARCHES: when the user asks for news or recent information, use the [WEB SEARCH] context already provided. Do NOT add topics to the queue, do NOT use [ADD_TOPIC] or [PUBLISH_NOW].\n\nCRITICAL RULE ON PREFERENCES/SETTINGS: use ONLY [SETPREF: key=value]. NEVER add [PUBLISH_NOW], [ADD_TOPIC] or [PRIORITIZE_TOPIC] — changing a preference does NOT mean they want a new video now.\nExamples: "make the text yellow" → [SETPREF: thumbnail_text_color=yellow] | "text at the top" → [SETPREF: thumbnail_text_position=top] | "no thumbnail text" → [SETPREF: thumbnail_show_text=false] | "larger text" → [SETPREF: thumbnail_text_scale=1.0]\n\nCRITICAL RULE ON TAGS: only use the tags listed above. Do NOT invent tags — they won't be executed.\n\nDECISION GUIDE — which tag to use:\n- "generate a thumbnail" → [GENERATE_THUMBNAIL: title]\n- "generate audio / let me hear the voice" → [GENERATE_AUDIO: text]\n- "write/generate a script" → [GENERATE_SCRIPT: topic]\n- "send me the video" → [SEND_VIDEO]\n- "create/publish this video / do it now" → [PUBLISH_NOW: title]\n- "next video about X / prioritize" → [PRIORITIZE_TOPIC: title]\n- "add to the queue" → [ADD_TOPIC: title]\n- "update channel description" → [UPDATE_DESCRIPTION: text]\n- "update channel keywords" → [UPDATE_KEYWORDS: kw1, kw2]\n- "remove topic N" → [REMOVE_TOPIC: N]\n- "remember this information" → [REMEMBER: fact]\n\nABSOLUTE RULES:\n- Always reply in {_AGENT_LANGUAGE} — non-negotiable\n- When asked to DO something on the channel → use the API tag, don't explain\n- When asked to develop a topic → do it immediately in full\n- Never say "I can't" — use the available tags or generate the content\n- Profile picture: impossible via API (Google limitation)\n- Channel name: impossible via API for personal accounts — tell user to go to YouTube Studio → Customization → Basic info, or convert to Brand Account\n"""

def _get_history(state: dict, chat_id: str) -> list:
    return state.get('chat_history', {}).get(str(chat_id), [])

def _save_history(state: dict, chat_id: str, history: list) -> None:
    if 'chat_history' not in state:
        state['chat_history'] = {}
    state['chat_history'][str(chat_id)] = history[-MAX_HISTORY:]
_SEARCH_KEYWORDS = ('notizie', 'news', 'ultime', 'recenti', 'oggi', 'this week', 'this month', 'cosa sta succedendo', 'updatementi', 'novità', 'annunci', 'annuncio', 'latest', 'recent', 'update', 'updates', "what's happening", 'announced', 'uscito', 'rilasciato', 'lanciato', 'released', 'launched')
_ACTION_KEYWORDS = ('crea', 'fai', 'produci', 'pubblica', 'carica', 'generate', 'start', 'lancia', 'make', 'create', 'publish', 'upload', 'generate', 'start', 'run', 'add to queue', 'aggiungi')

def _needs_web_search(text: str) -> bool:
    t = text.lower()
    has_search = any((k in t for k in _SEARCH_KEYWORDS))
    has_action = any((k in t for k in _ACTION_KEYWORDS))
    return has_search and (not has_action)

def _extract_search_query(text: str) -> str:
    """Extract the search query from the user message."""
    import re
    patterns = ['news about (.+)', 'news on (.+)', 'updatementi su (.+)', 'latest on (.+)', 'latest (?:news )?about (.+)', 'what is happening (?:with |about )?(.+)', 'what is happening (?:with |about )?(.+)', 'search for (.+)', 'find (.+)', 'tell me (?:about )?(.+)', 'about (.+)']
    t = text.lower().strip()
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return m.group(1).strip()
    for prefix in ('latest news', 'breaking news', 'notizie', 'news', 'updatementi'):
        if t.startswith(prefix):
            return t[len(prefix):].strip() or text
    return text

def _is_preference_list_request(text: str) -> bool:
    t = text.lower()
    return 'preferenz' in t and any((k in t for k in ('mostra', 'lista', 'vedere', 'vedi', 'quali', 'attuali', 'dimmi')))
_PREF_KEYWORDS = ('stile', 'style', 'thumbnail', 'copertina', 'pacing', 'tono', 'language', 'language', 'clip', 'montaggio', 'volume', 'musica', 'durata', 'argomenti', 'topic', 'evita', 'preferisci', 'preferenza', 'impostazione', 'setting', 'cambia', 'modifica', 'set', 'setta', 'metti', 'usa', 'change', 'set', 'update', 'modify', 'use')

def _is_pref_only_request(text: str) -> bool:
    """Detect a settings request without intent to create a video."""
    t = text.lower()
    has_pref = any((k in t for k in _PREF_KEYWORDS))
    has_action = any((k in t for k in _ACTION_KEYWORDS))
    return has_pref and (not has_action)

def _format_preference_updates(modifiche: dict) -> str:
    lines = ['✅ Preferences updated:']
    for chiave, valore in modifiche.items():
        val = ', '.join(valore) if isinstance(valore, list) else str(valore)
        lines.append(f'• <b>{html.escape(chiave)}</b>: <code>{html.escape(val)}</code>')
    return '\n'.join(lines)

def _ask_ai(user_text: str, history: list, state: dict) -> tuple[str, list]:
    from moduli.ai_client import chat_with_history
    from moduli.memoria import come_contesto
    from moduli.web_search import cerca_notizie
    system_parts = [SYSTEM_PROMPT]
    memoria = come_contesto()
    if memoria:
        system_parts.append(memoria)
    from moduli.preferenze import come_contesto as pref_contesto
    system_parts.append(pref_contesto())
    queue = state.get('topic_queue', [])
    recent = state.get('recent_topics', [])
    ore_publish = publish_hours(state)
    ore_trigger = trigger_hours(state)
    vpd = state.get('videos_per_day', 1)
    video_ids = state.get('video_ids', [])
    video_links = ', '.join((f'https://youtu.be/{v}' for v in video_ids[:5])) if video_ids else 'none'
    is_search = _needs_web_search(user_text)
    if is_search:
        query = _extract_search_query(user_text)
        notizie = cerca_notizie(query, max_results=6)
        if notizie:
            system_parts.append(f"[LIVE WEB SEARCH — query: '{query}']\n{notizie}")
    _ora_locale = datetime.now().astimezone()
    _giorni = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']
    _data_str = f"{_giorni[_ora_locale.weekday()]} {_ora_locale.strftime('%d/%m/%Y')}"
    _tz_str = _ora_locale.strftime('%Z') or 'local time'
    system_parts.append(f"[CURRENT CONTEXT — {_data_str}, time {_ora_locale.strftime('%H:%M')} ({_tz_str}; {datetime.now(timezone.utc).strftime('%H:%M')} UTC)]\nIMPORTANT: use the EXACT date and time above. Do not calculate or invent them.\nVideos per day: {vpd} | Automatic pipeline: {ore_trigger} UTC | Publish: {ore_publish} UTC\nQueued topics ({len(queue)}):\n{(chr(10).join((f'  {i + 1}. {t}' for i, t in enumerate(queue))) if queue else '  none')}\nIMPORTANT: when the user says 'make topic N' or 'create topic N', copy the EXACT text of topic N above into [PUBLISH_NOW: exact text].\nRecent produced topics: {(', '.join(recent[:5]) if recent else 'none')}\nPublished videos: {video_links}\nIMPORTANT: answer questions about published videos with the links above. Do not use [VIDEO] or similar tags.")
    system = '\n\n'.join(system_parts)
    effective_text = user_text
    if is_search:
        effective_text = f'[INFORMATION ONLY — do not queue topics or use PUBLISH_NOW, ADD_TOPIC or PRIORITIZE_TOPIC]\n{user_text}'
    try:
        reply = chat_with_history(system, history, effective_text)
    except Exception as e:
        return (f'⚠️ AI error: {e}', history)
    new_history = history + [{'role': 'user', 'content': user_text}, {'role': 'assistant', 'content': reply}]
    return (reply, new_history)

def _execute_confirmed_action(state: dict, action: dict) -> str:
    """Run an action that was previously queued for explicit user confirmation."""
    action_type = action.get('type')
    payload = (action.get('payload') or '').strip()
    if action_type == 'PUBLISH_NOW':
        queue = state.get('topic_queue', [])
        if payload and (not queue or queue[0] != payload):
            queue.insert(0, payload)
        state['topic_queue'] = queue
        state['force_run'] = True
        state['publish_immediately'] = True
        checkpoint = 'output/pipeline_checkpoint.json'
        if os.path.exists(checkpoint):
            os.remove(checkpoint)
        return f'Confirmed: immediate pipeline for <i>{_h(payload)}</i>.'
    if action_type == 'RENAME_CHANNEL':
        from moduli.canale import aggiorna_canale
        res = aggiorna_canale(title=payload)
        if 'title_error' in res:
            return _h(res['title_error'])
        return f'Channel renamed to <b>{_h(payload)}</b>.'
    if action_type == 'UPDATE_DESCRIPTION':
        from moduli.canale import aggiorna_canale
        aggiorna_canale(description=payload)
        return 'Channel description updated.'
    if action_type == 'UPDATE_KEYWORDS':
        from moduli.canale import aggiorna_canale
        aggiorna_canale(keywords=payload)
        return 'Channel keywords updated.'
    if action_type in {'VIDEO_TITLE', 'VIDEO_DESC', 'VIDEO_TAGS'}:
        from moduli.pubblica import aggiorna_video
        parts = payload.split('|', 1)
        if len(parts) != 2:
            raise ValueError('Invalid format: use video_id | value')
        vid, value = (parts[0].strip(), parts[1].strip())
        if action_type == 'VIDEO_TITLE':
            aggiorna_video(vid, title=value)
            return f'Title updated for <a href="https://youtu.be/{_h(vid)}">youtu.be/{_h(vid)}</a>.'
        if action_type == 'VIDEO_DESC':
            aggiorna_video(vid, description=value)
            return f'Description updated for <a href="https://youtu.be/{_h(vid)}">youtu.be/{_h(vid)}</a>.'
        tags = [t.strip() for t in value.split(',') if t.strip()]
        aggiorna_video(vid, tags=tags)
        return f'Tags updated for <a href="https://youtu.be/{_h(vid)}">youtu.be/{_h(vid)}</a>.'
    if action_type == 'VIDEO_THUMB':
        from moduli.pubblica import aggiorna_video
        thumb = 'output/thumbnail.jpg'
        if not os.path.exists(thumb):
            raise FileNotFoundError('Thumbnail not found at output/thumbnail.jpg')
        res = aggiorna_video(payload, thumbnail_path=thumb)
        if res.get('thumbnail_error'):
            raise RuntimeError(res['thumbnail_error'])
        return f'Thumbnail uploaded for <a href="https://youtu.be/{_h(payload)}">youtu.be/{_h(payload)}</a>.'
    if action_type == 'REMOVE_TOPIC':
        idx = int(payload) - 1
        queue = state.get('topic_queue', [])
        if idx < 0 or idx >= len(queue):
            raise IndexError(f'Topic {payload} does not exist (queue contains {len(queue)} items)')
        removed = queue.pop(idx)
        state['topic_queue'] = queue
        return f'Topic removed: <i>{_h(removed)}</i>. Remaining: {len(queue)}.'
    if action_type == 'RESTART_EDITING':
        checkpoint = 'output/pipeline_checkpoint.json'
        if os.path.exists(checkpoint):
            os.remove(checkpoint)
        state['force_run'] = True
        return 'Checkpoint cleared; pipeline restarted.'
    if action_type == 'STOP_PIPELINE':
        state['abort_pipeline'] = True
        state.pop('force_run', None)
        return 'Stop confirmed. The pipeline will stop at the next checkpoint.'
    raise ValueError(f'Unknown action: {action_type}')

def _execute_actions(reply: str, state: dict, is_search: bool=False, is_pref_only: bool=False) -> tuple[str, list, list, list, list, list]:
    """Execute recognized action tags from the AI response. Return clean text, topics, memory changes, API results and deferred tasks."""
    import re
    from moduli.memoria import aggiungi as mem_aggiungi, _save as mem_save, _load as mem_load
    added_topics = []
    saved_memories = []
    removed_memories = []
    api_results = []
    deferred_tasks = []
    queue = state.get('topic_queue', [])

    def _add_topic(m):
        topic = m.group(1).strip()
        queue.append(topic)
        added_topics.append(f'{topic} (queued)')
        return ''

    def _priorita_topic(m):
        topic = m.group(1).strip()
        if not queue or queue[0] != topic:
            queue.insert(0, topic)
            added_topics.append(f'{topic} (at the front — next video)')
        return ''

    def _forza_ora(m):
        topic = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'PUBLISH_NOW', topic, f'start and publish now: {topic}'))
        return ''

    def _ricorda(m):
        testo = m.group(1).strip()
        mem_aggiungi(testo)
        saved_memories.append(testo)
        return ''

    def _setpref(m):
        from moduli.preferenze import carica, salva, DEFAULT_PREF
        raw = m.group(1).strip()
        if '=' not in raw:
            return ''
        chiave, _, valore = raw.partition('=')
        chiave = chiave.strip()
        valore = valore.strip().strip('"').strip("'")
        if chiave not in DEFAULT_PREF:
            return ''
        pref = carica()
        default_val = DEFAULT_PREF[chiave]
        if isinstance(default_val, list):
            pref[chiave] = [v.strip() for v in valore.split(',') if v.strip()]
        elif isinstance(default_val, (int, float)):
            try:
                pref[chiave] = type(default_val)(valore)
            except ValueError:
                return ''
        else:
            pref[chiave] = valore
        salva(pref)
        api_results.append(f'⚙️ Preference updated: <b>{_h(chiave)}</b> = <code>{_h(pref[chiave])}</code>')
        return ''

    def _dimentica(m):
        testo = m.group(1).strip().lower()
        memories = mem_load()
        nuove = [x for x in memories if testo not in x['text'].lower()]
        rimossi = [x['text'] for x in memories if testo in x['text'].lower()]
        mem_save(nuove)
        removed_memories.extend(rimossi)
        return ''

    def _rinomina_canale(m):
        nome = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'RENAME_CHANNEL', nome, f'rename channel: {nome}'))
        return ''

    def _aggiorna_desc(m):
        from moduli.canale import aggiorna_canale
        desc = m.group(1).strip()
        try:
            aggiorna_canale(description=desc)
            api_results.append('✅ Channel description updated.')
        except Exception as e:
            api_results.append(f'❌ Description update failed: {_h(str(e))}')
        return ''

    def _aggiorna_keywords(m):
        from moduli.canale import aggiorna_canale
        kw = m.group(1).strip()
        try:
            aggiorna_canale(keywords=kw)
            api_results.append('✅ Channel keywords updated.')
        except Exception as e:
            api_results.append(f'❌ Keyword update failed: {_h(str(e))}')
        return ''

    def _video_titolo(m):
        payload = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'VIDEO_TITLE', payload, 'update video title'))
        return ''

    def _video_desc(m):
        payload = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'VIDEO_DESC', payload, 'update video description'))
        return ''

    def _video_tags(m):
        payload = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'VIDEO_TAGS', payload, 'update video tags'))
        return ''

    def _elimina_topic(m):
        raw = m.group(1).strip()
        try:
            idx = int(raw) - 1
        except ValueError:
            api_results.append(f'❌ [REMOVE_TOPIC] invalid number: {_h(raw)}')
            return ''
        q = state.get('topic_queue', [])
        if idx < 0 or idx >= len(q):
            api_results.append(f'❌ Topic {_h(raw)} does not exist (queue contains {len(q)} items)')
            return ''
        rimosso = q.pop(idx)
        state['topic_queue'] = q
        api_results.append(f'🗑 Topic removed: <i>{_h(rimosso)}</i> — remaining: {len(q)}')
        return ''

    def _riavvia_montaggio(m):
        api_results.append(_queue_pending_action(state, 'RESTART_EDITING', '', 'restart editing'))
        return ''

    def _blocca_pipeline(m):
        api_results.append(_queue_pending_action(state, 'STOP_PIPELINE', '', 'stop pipeline'))
        return ''

    def _genera_copertina(m):
        deferred_tasks.append(('thumbnail', m.group(1).strip()))
        return ''

    def _genera_audio(m):
        deferred_tasks.append(('audio', m.group(1).strip()))
        return ''

    def _genera_script(m):
        deferred_tasks.append(('script', m.group(1).strip()))
        return ''

    def _invia_video(m):
        deferred_tasks.append(('video', None))
        return ''

    def _video_thumb(m):
        vid = m.group(1).strip()
        api_results.append(_queue_pending_action(state, 'VIDEO_THUMB', vid, f'update video thumbnail {vid}'))
        return ''
    clean = re.sub('\\[GENERATE_THUMBNAIL:\\s*([^\\]]+)\\]', _genera_copertina, reply)
    clean = re.sub('\\[GENERATE_AUDIO:\\s*([^\\]]+)\\]', _genera_audio, clean)
    clean = re.sub('\\[GENERATE_SCRIPT:\\s*([^\\]]+)\\]', _genera_script, clean)
    clean = re.sub('\\[SEND_VIDEO\\]', _invia_video, clean)
    if is_search or is_pref_only:
        clean = re.sub('\\[ADD_TOPIC:\\s*[^\\]]+\\]', '', clean)
        clean = re.sub('\\[PRIORITIZE_TOPIC:\\s*[^\\]]+\\]', '', clean)
        clean = re.sub('\\[PUBLISH_NOW:\\s*[^\\]]+\\]', '', clean)
    else:
        clean = re.sub('\\[ADD_TOPIC:\\s*([^\\]]+)\\]', _add_topic, clean)
        clean = re.sub('\\[PRIORITIZE_TOPIC:\\s*([^\\]]+)\\]', _priorita_topic, clean)
        clean = re.sub('\\[PUBLISH_NOW:\\s*([^\\]]+)\\]', _forza_ora, clean)
    clean = re.sub('\\[REMEMBER:\\s*([^\\]]+)\\]', _ricorda, clean)
    clean = re.sub('\\[SETPREF:\\s*([^\\]]+)\\]', _setpref, clean)
    clean = re.sub('\\[FORGET:\\s*([^\\]]+)\\]', _dimentica, clean)
    clean = re.sub('\\[RENAME_CHANNEL:\\s*([^\\]]+)\\]', _rinomina_canale, clean)
    clean = re.sub('\\[UPDATE_DESCRIPTION:\\s*([^\\]]+)\\]', _aggiorna_desc, clean)
    clean = re.sub('\\[UPDATE_KEYWORDS:\\s*([^\\]]+)\\]', _aggiorna_keywords, clean)
    clean = re.sub('\\[VIDEO_TITLE:\\s*([^\\]]+)\\]', _video_titolo, clean)
    clean = re.sub('\\[VIDEO_DESC:\\s*([^\\]]+)\\]', _video_desc, clean)
    clean = re.sub('\\[VIDEO_TAGS:\\s*([^\\]]+)\\]', _video_tags, clean)
    clean = re.sub('\\[VIDEO_THUMB:\\s*([^\\]]+)\\]', _video_thumb, clean)
    clean = re.sub('\\[REMOVE_TOPIC:\\s*([^\\]]+)\\]', _elimina_topic, clean)
    clean = re.sub('\\[RESTART_EDITING\\]', _riavvia_montaggio, clean)
    clean = re.sub('\\[STOP_PIPELINE\\]', _blocca_pipeline, clean)
    if added_topics:
        state['topic_queue'] = queue
    return (clean.strip(), added_topics, saved_memories, removed_memories, api_results, deferred_tasks)
from moduli.state_io import load_state as _load_state, save_state as _save_state
from moduli.scheduling import publish_hours, trigger_hours, PUBLISH_SPREADS

def _publish_hours(state: dict) -> list[int]:
    return publish_hours(state)

def _trigger_hours(state: dict) -> list[int]:
    return trigger_hours(state)

def _next_schedule(state: dict):
    now = datetime.now(timezone.utc)
    done = state.get('runs_today', {}).get(now.strftime('%Y-%m-%d'), 0)
    if done >= state.get('videos_per_day', 1):
        now = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    publish = _publish_hours(state)
    trigger = _trigger_hours(state)
    upcoming = []
    for idx, (trigger_hour, publish_hour) in enumerate(zip(trigger, publish)):
        trigger_dt = now.replace(hour=trigger_hour, minute=0, second=0, microsecond=0)
        publish_dt = now.replace(hour=publish_hour, minute=0, second=0, microsecond=0)
        if publish_dt <= trigger_dt:
            publish_dt += timedelta(days=1)
        if trigger_dt <= now:
            trigger_dt += timedelta(days=1)
            publish_dt += timedelta(days=1)
        upcoming.append((trigger_dt, publish_dt, idx))
    upcoming.sort(key=lambda item: item[0])
    return upcoming[0] if upcoming else (None, None, done)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("👋 <b>YouTube AI Agent is ready</b>\n\nI produce and publish videos on the configured schedule.\n\n<b>📹 Pipeline:</b>\n/status — current status\n/recap — recent video analytics\n/run — start the pipeline\n/publishnow &lt;topic&gt; — publish immediately\n/skip — skip today's video\n/setvideosperday &lt;1-5&gt; — videos per day\n/setpublish &lt;hour1&gt; [hour2] — publication times in UTC\n/autoscheduling on|off — analytics-based scheduling\n/schedule — current schedule\n/upcoming — next production and publication\n/queue — queued topics\n/topic &lt;text&gt; — add a topic\n/deltopic &lt;number&gt; — remove a topic\n\n<b>📺 Channel:</b>\n/channel — channel statistics\n/setdesc &lt;text&gt; — update description\n/video — recent videos\n/playlist — channel playlists\n/newplaylist &lt;name&gt; — create a playlist\n/comments &lt;videoId&gt; — read comments\n\n<b>🧠 Memory:</b>\n/memory — saved memories\n/forget &lt;n&gt; — remove a memory\n\n💬 Send a message to talk to the AI.\n\n<b>Examples:</b>\n• <i>generate a test thumbnail</i> → standalone thumbnail\n• <i>make the next video about X</i> → full pipeline", parse_mode='HTML')

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    last = state.get('last_run_date', 'Mai')
    queue = state.get('topic_queue', [])
    recent = state.get('recent_topics', [])
    last_video = state.get('video_ids', [None])[0]
    ps = state.get('pipeline_status')
    if ps:
        pct = ps.get('pct')
        attivita = f"🔄 Producing — step: <b>{_h(ps.get('step', '?'))}</b>" + (f' ({pct}%)' if pct else '') + f"\n   updated {_h(ps.get('updated_at', ''))}"
    else:
        trigger_dt, _, _ = _next_schedule(state)
        if trigger_dt:
            attivita = f"⏳ Waiting — next pipeline: {trigger_dt.strftime('%d/%m %H:%M UTC')}"
        else:
            attivita = '⏳ Waiting — no schedule configured'
    try:
        from moduli.video_ai import riassunto as _riassunto_clip
        riga_clip = f'🎞 Clip: {_h(_riassunto_clip())}\n'
    except Exception:
        riga_clip = ''
    msg = f"📡 <b>Agent status</b>\n\n{attivita}\n\n🗓 Last run: {last}\n📋 Queued topics: {len(queue)}\n📹 Videos produced: {len(state.get('video_ids', []))}\n{riga_clip}"
    if last_video:
        msg += f'🔗 Latest: https://youtu.be/{last_video}\n'
    if recent:
        msg += f'\n<b>Recent topics:</b>\n' + '\n'.join((f'• {_h(t)}' for t in recent[:5]))
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_preferenze(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.preferenze import formato_html
    await update.message.reply_text(formato_html(), parse_mode='HTML')

async def cmd_setpref(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.preferenze import aggiorna, DEFAULT_PREF
    if len(ctx.args) < 2:
        await update.message.reply_text('Usage: /setpref <key> <value>\nKeys: ' + ', '.join(DEFAULT_PREF.keys()))
        return
    chiave = ctx.args[0]
    valore = ' '.join(ctx.args[1:])
    if chiave not in DEFAULT_PREF:
        await update.message.reply_text(f"Unknown key: {chiave}\nAvailable: {', '.join(DEFAULT_PREF.keys())}")
        return
    try:
        pref = aggiorna(chiave, valore)
    except ValueError:
        await update.message.reply_text(f'Invalid value for {chiave}.')
        return
    await update.message.reply_text(f'✅ <b>{_h(chiave)}</b> updated: <code>{_h(pref[chiave])}</code>', parse_mode='HTML')

async def cmd_recap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('📊 Loading analytics...')
    loop = asyncio.get_event_loop()
    try:
        from moduli.analytics import leggi_performance
        videos = await loop.run_in_executor(None, lambda: leggi_performance(n_video=10))
        if not videos:
            await update.message.reply_text('No videos found on this channel.')
            return
        lines = ['📊 <b>Recent video performance:</b>\n']
        for v in videos:
            retention = int(v.get('avg_view_duration_seconds', 0) / max(v.get('duration_seconds', 480), 1) * 100)
            lines.append(f"▪️ <b>{_h(v['title'][:50])}</b>\n   👁 {v['views']} views · 👀 {v.get('impressions', 0)} impr · 📈 CTR {v.get('ctr_percent', 0)}%\n   ❤️ {v['likes']} · 💬 {v['comments']} · ⏱ {retention}% retention · ⏰ {int(v.get('avg_view_duration_seconds', 0))}s avg")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f'❌ Analytics error: {e}')

async def cmd_forza(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    state['force_run'] = True
    state.pop('publish_immediately', None)
    _save_state(state)
    await update.message.reply_text('⚡ <b>Pipeline requested!</b>\nIt will start within 60 seconds.', parse_mode='HTML')

async def cmd_forzaora(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    topic = ' '.join(ctx.args).strip() if ctx.args else ''
    state = _load_state()
    if topic:
        queue = state.get('topic_queue', [])
        queue.insert(0, topic)
        state['topic_queue'] = queue
    state['force_run'] = True
    state['publish_immediately'] = True
    _save_state(state)
    detail = f'\nTopic: <i>{html.escape(topic)}</i>' if topic else ''
    await update.message.reply_text(f'⚡ <b>Pipeline requested with immediate publication.</b>{detail}\nIt will start within 60 seconds.', parse_mode='HTML')

async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    vpd = state.get('videos_per_day', 1)
    runs = state.get('runs_today', {})
    runs[today] = vpd
    state['runs_today'] = runs
    state['last_run_date'] = today
    state.pop('force_run', None)
    state.pop('publish_immediately', None)
    _save_state(state)
    await update.message.reply_text(f"⏭️ Today's skipped videos: {vpd}/{vpd}.")

async def cmd_abort(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    state['abort_pipeline'] = True
    state.pop('force_run', None)
    _save_state(state)
    await update.message.reply_text('⛔ <b>Stop requested.</b>\n\nThe pipeline will stop at the next step.\n<i>If editing is already running, it will finish before stopping.</i>', parse_mode='HTML')

async def cmd_coda(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get('topic_queue', [])
    if not queue:
        await update.message.reply_text('📋 Queue empty — the next topic will be generated automatically.')
    else:
        msg = '📋 <b>Queued topics:</b>\n' + '\n'.join((f'{i + 1}. {_h(t)}' for i, t in enumerate(queue)))
        await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = ' '.join(ctx.args).strip() if ctx.args else ''
    if not text:
        await update.message.reply_text('Usage: /topic <topic text>')
        return
    state = _load_state()
    queue = state.get('topic_queue', [])
    queue.append(text)
    state['topic_queue'] = queue
    _save_state(state)
    await update.message.reply_text(f'✅ <b>Topic queued</b>\n\n📌 <i>{_h(text)}</i>\n\nPosition {len(queue)} in the queue.', parse_mode='HTML')

async def cmd_setvideogiorno(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text('Usage: /setvideosperday <1-5>')
        return
    try:
        n = int(ctx.args[0])
        if not 1 <= n <= 5:
            raise ValueError
    except ValueError:
        await update.message.reply_text('Invalid number. Choose a value from 1 to 5.')
        return
    publish_spreads = PUBLISH_SPREADS
    state = _load_state()
    state['videos_per_day'] = n
    state['publish_hours_utc'] = publish_spreads[n]
    state.pop('trigger_hours_utc', None)
    _save_state(state)
    trigger_str = ', '.join((f'{h:02d}:00' for h in _trigger_hours(state)))
    publish_str = ', '.join((f'{h:02d}:00' for h in _publish_hours(state)))
    await update.message.reply_text(f'✅ <b>{n} videos per day</b>\n\n🎬 Automatic pipeline: {trigger_str} UTC\n📅 Publication: {publish_str} UTC\n\nUse /autoscheduling to optimize times automatically.', parse_mode='HTML')

async def cmd_autoscheduling(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    arg = ctx.args[0].lower() if ctx.args else ''
    if arg not in ('on', 'off'):
        await update.message.reply_text('Usage: /autoscheduling on or /autoscheduling off')
        return
    state = _load_state()
    state['auto_scheduling'] = arg == 'on'
    _save_state(state)
    if arg == 'on':
        await update.message.reply_text('🤖 <b>Automatic scheduling enabled</b>\n\nThe agent will analyze performance and select production and publication times.', parse_mode='HTML')
    else:
        await update.message.reply_text('⏹ Automatic scheduling disabled. Manual times apply.')

async def cmd_orari(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    vpd = state.get('videos_per_day', 1)
    publish = _publish_hours(state)
    trigger = _trigger_hours(state)
    auto = state.get('auto_scheduling', False)
    done = state.get('runs_today', {}).get(datetime.now(timezone.utc).strftime('%Y-%m-%d'), 0)
    trigger_str = '\n'.join((f"  {i + 1}. Production at {h:02d}:00 UTC → publish at {(f'{publish[i]:02d}' if i < len(publish) else '?')}:00 UTC" for i, h in enumerate(trigger)))
    await update.message.reply_text(f"📅 <b>Current schedule</b>\n\n📹 Videos per day: {vpd}\n✅ Produced today: {done}/{vpd}\n🤖 Automatic scheduling: {('ON' if auto else 'OFF')}\n\n{trigger_str}", parse_mode='HTML')

async def cmd_prossimi(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get('topic_queue', [])
    vpd = state.get('videos_per_day', 1)
    now = datetime.now(timezone.utc)
    done = state.get('runs_today', {}).get(now.strftime('%Y-%m-%d'), 0)
    remaining = max(0, vpd - done)
    trigger_dt, publish_dt, idx = _next_schedule(state)
    next_topic = queue[0] if queue else 'generated automatically'
    if trigger_dt is None:
        await update.message.reply_text('No schedule configured.')
        return
    await update.message.reply_text(f"⏭️ <b>Upcoming events</b>\n\n🎬 Next pipeline: {trigger_dt.strftime('%d/%m/%Y %H:%M UTC')}\n📅 Next publication: {publish_dt.strftime('%d/%m/%Y %H:%M UTC')}\n📹 Videos remaining today: {remaining}/{vpd}\n📌 Next topic: <i>{html.escape(next_topic)}</i>", parse_mode='HTML')

async def cmd_setpubblica(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text('Usage: /setpublish &lt;hour1&gt; [hour2 ...]\nExample: /setpublish 14 → one video at 14:00 UTC\nExample: /setpublish 12 20 → first video at 12:00, second at 20:00 UTC\n\nProduction starts automatically 3 hours before each publication time.', parse_mode='HTML')
        return
    try:
        ore = [int(a) for a in ctx.args]
        if any((not 0 <= o <= 23 for o in ore)):
            raise ValueError
    except ValueError:
        await update.message.reply_text('Invalid hours. Use numbers from 0 to 23.')
        return
    ore = sorted(set(ore))
    state = _load_state()
    state['publish_hours_utc'] = ore
    state.pop('trigger_hours_utc', None)
    era_auto = bool(state.pop('auto_scheduling', False))
    _save_state(state)
    richiesti = len(ore)
    ore = _publish_hours(state)
    trigger_ore = _trigger_hours(state)
    lines = [f'  Video {i + 1}: production at <b>{t:02d}:00</b>, publication at <b>{p:02d}:00</b> UTC' for i, (t, p) in enumerate(zip(trigger_ore, ore))]
    nota = '\n\n🤖 Automatic scheduling is off; manual times apply. Enable it with <code>/autoscheduling on</code>.' if era_auto else ''
    if richiesti > len(ore):
        nota += f"\n\n⚠️ You entered {richiesti} times but produce {state.get('videos_per_day', 1)} videos per day; using only {('the first' if len(ore) == 1 else f'the first {len(ore)}')}. To use all times: <code>/setvideosperday {richiesti}</code>."
    await update.message.reply_text('✅ Schedule updated:\n' + '\n'.join(lines) + nota, parse_mode='HTML')

async def cmd_deltopic(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = _load_state()
    queue = state.get('topic_queue', [])
    if not queue:
        await update.message.reply_text('📋 Queue is already empty.')
        return
    if not ctx.args:
        await update.message.reply_text('Usage: /deltopic <number>\n\nUse /queue to see topic numbers.')
        return
    try:
        idx = int(ctx.args[0]) - 1
        if idx < 0 or idx >= len(queue):
            raise ValueError
    except ValueError:
        await update.message.reply_text(f'Invalid number. The queue contains {len(queue)} topic.')
        return
    rimosso = queue.pop(idx)
    state['topic_queue'] = queue
    _save_state(state)
    await update.message.reply_text(f'🗑 <b>Topic removed:</b>\n<i>{_h(rimosso)}</i>\n\nTopics remaining in the queue: {len(queue)}', parse_mode='HTML')

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.message.chat_id)
    state = _load_state()
    if 'chat_history' in state and chat_id in state['chat_history']:
        state['chat_history'][chat_id] = []
        _save_state(state)
    await update.message.reply_text('🔄 <b>Conversation reset.</b>\nThe AI no longer remembers earlier messages in this chat. Long-term memory (<code>/memory</code>) is unchanged.', parse_mode='HTML')

async def cmd_memoria(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.memoria import lista
    memories = lista()
    if not memories:
        await update.message.reply_text('🧠 Memory is empty.')
        return
    righe = '\n'.join((f"{i + 1}. {_h(m['text'])} <i>({_h(m['data'])})</i>" for i, m in enumerate(memories)))
    await update.message.reply_text(f'🧠 <b>Long-term memory:</b>\n\n{righe}', parse_mode='HTML')

async def cmd_dimentica(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from moduli.memoria import rimuovi, svuota, lista
    if ctx.args and ctx.args[0].lower() == 'tutto':
        svuota()
        await update.message.reply_text('🗑 All memories cleared.')
        return
    if not ctx.args:
        await update.message.reply_text('Usage: /forget <number> or /forget all\nUse /memory to see memory numbers.')
        return
    try:
        idx = int(ctx.args[0]) - 1
        rimossa = rimuovi(idx)
        if rimossa:
            await update.message.reply_text(f'🗑 Removed: <i>{rimossa}</i>', parse_mode='HTML')
        else:
            await update.message.reply_text('Invalid number.')
    except ValueError:
        await update.message.reply_text('Use a number. Example: /forget 2')

async def cmd_conferma(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    action_id = ctx.args[0].strip() if ctx.args else ''
    if not action_id:
        await update.message.reply_text('Usage: /confirm <id>')
        return
    state = _load_state()
    pending = _pending_actions(state)
    action = next((a for a in pending if a.get('id') == action_id), None)
    if not action:
        _save_state(state)
        await update.message.reply_text('Confirmation not found or expired.')
        return
    try:
        result = _execute_confirmed_action(state, action)
        state['pending_actions'] = [a for a in pending if a.get('id') != action_id]
        _save_state(state)
        await update.message.reply_text(f'✅ {result}', parse_mode='HTML')
    except Exception as e:
        _save_state(state)
        await update.message.reply_text(f'❌ Confirmed action failed: {_h(e)}', parse_mode='HTML')

async def cmd_annulla(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    action_id = ctx.args[0].strip() if ctx.args else ''
    if not action_id:
        await update.message.reply_text('Usage: /cancel <id>')
        return
    state = _load_state()
    pending = _pending_actions(state)
    remaining = [a for a in pending if a.get('id') != action_id]
    if len(remaining) == len(pending):
        _save_state(state)
        await update.message.reply_text('Action not found or already expired.')
        return
    state['pending_actions'] = remaining
    _save_state(state)
    await update.message.reply_text('Action cancelled.')

def _run_canale(fn, *args, **kwargs):
    from moduli.canale import info_canale, aggiorna_canale, lista_video, lista_playlist, crea_playlist, lista_commenti, rispondi_commento, elimina_commento
    funcs = {'info_canale': info_canale, 'update_canale': aggiorna_canale, 'lista_video': lista_video, 'lista_playlist': lista_playlist, 'crea_playlist': crea_playlist, 'lista_commenti': lista_commenti, 'rispondi_commento': rispondi_commento, 'elimina_commento': elimina_commento}
    return funcs[fn](*args, **kwargs)

async def cmd_canale(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🔄 Loading channel information...')
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(None, _run_canale, 'info_canale')
        msg = f"📺 <b>{_h(info['title'])}</b>\n\n👥 Subscribers: {info['subscribers']:,}\n👁 Views: {info['views']:,}\n📹 Video: {info['video_count']}\n🌍 Country: {_h(info['country'])}\n\n📝 <b>Description:</b>\n{_h(info['description'][:300]) or '—'}\n\n🔑 <b>Keyword:</b> {_h(info['keywords'][:200]) or '—'}"
    except Exception as e:
        msg = f'❌ Error: {e}'
    await update.message.reply_text(msg, parse_mode='HTML')

async def cmd_setdesc(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    desc = ' '.join(ctx.args).strip() if ctx.args else ''
    if not desc:
        await update.message.reply_text('Usage: /setdesc <new description>')
        return
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _run_canale('update_canale', description=desc))
        await update.message.reply_text('✅ Channel description updated.')
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')

async def cmd_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🔄 Loading videos...')
    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, _run_canale, 'lista_video')
        if not videos:
            await update.message.reply_text('No videos found.')
            return
        lines = [f'📹 <b>Recent videos:</b>']
        for v in videos:
            lines.append(f"▪️ <a href='https://youtu.be/{v['video_id']}'>{_h(v['title'][:50])}</a> — {v['published']}")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')

async def cmd_playlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🔄 Loading playlists...')
    loop = asyncio.get_event_loop()
    try:
        playlists = await loop.run_in_executor(None, _run_canale, 'lista_playlist')
        if not playlists:
            await update.message.reply_text('No playlists found.')
            return
        lines = ['📋 <b>Playlist:</b>']
        for p in playlists:
            lines.append(f"▪️ {_h(p['title'])} ({p['count']} video) — <code>{p['id']}</code>")
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')

async def cmd_nuovaplaylist(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    nome = ' '.join(ctx.args).strip() if ctx.args else ''
    if not nome:
        await update.message.reply_text('Usage: /newplaylist <name>')
        return
    loop = asyncio.get_event_loop()
    try:
        pid = await loop.run_in_executor(None, lambda: _run_canale('crea_playlist', nome))
        await update.message.reply_text(f'✅ Playlist <b>{nome}</b> created.\nID: <code>{pid}</code>', parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')

async def cmd_commenti(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    video_id = ctx.args[0] if ctx.args else ''
    if not video_id:
        await update.message.reply_text('Usage: /comments <videoId>')
        return
    loop = asyncio.get_event_loop()
    try:
        commenti = await loop.run_in_executor(None, lambda: _run_canale('lista_commenti', video_id))
        if not commenti:
            await update.message.reply_text('No comments found.')
            return
        lines = [f'💬 <b>Comments:</b>']
        for c in commenti:
            lines.append(f"<b>{_h(c['author'])}</b> (❤️{c['likes']})\n{_h(c['text'][:150])}\n<code>{c['id']}</code>")
        await update.message.reply_text('\n\n'.join(lines), parse_mode='HTML')
    except Exception as e:
        await update.message.reply_text(f'❌ Error: {e}')

async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    caption = (msg.caption or '').strip().lower()
    state_for_scope = _load_state()
    queue_for_scope = state_for_scope.get('topic_queue', [])
    if not caption or 'next' in caption or 'prossimo' in caption:
        scope = 'next'
    elif 'all' in caption or 'all' in caption or 'sempre' in caption:
        scope = 'all'
    else:
        import re as _re
        num_match = _re.search('\\d+', caption)
        if num_match:
            idx = int(num_match.group()) - 1
            if 0 <= idx < len(queue_for_scope):
                scope = queue_for_scope[idx]
            else:
                await msg.reply_text(f'Invalid topic number. You have {len(queue_for_scope)} queued topics.')
                return
        else:
            scope = caption
    if msg.photo:
        media_type = 'thumbnail'
        file_obj = msg.photo[-1]
        folder = 'assets/custom/thumbnails'
        ext = '.jpg'
    elif msg.video or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith('video')):
        media_type = 'video'
        file_obj = msg.video or msg.document
        folder = 'assets/custom/clips'
        ext = '.mp4'
    elif msg.audio or msg.voice or (msg.document and msg.document.mime_type and msg.document.mime_type.startswith('audio')):
        media_type = 'audio'
        file_obj = msg.audio or msg.voice or msg.document
        folder = 'assets/custom/audio'
        mime = getattr(file_obj, 'mime_type', 'audio/mpeg')
        ext = '.ogg' if msg.voice else '.mp3' if 'mpeg' in mime or 'mp3' in mime else '.m4a' if 'm4a' in mime or 'mp4' in mime else '.ogg'
    else:
        await msg.reply_text('Unsupported format. Send a photo, video (MP4) or audio (MP3/M4A).')
        return
    os.makedirs(folder, exist_ok=True)
    file_id = file_obj.file_id
    fname = f'{file_id[:16]}{ext}'
    dest = os.path.join(folder, fname)
    await msg.reply_text(f'Received {media_type} — saving...')
    tg_file = await ctx.bot.get_file(file_id)
    await tg_file.download_to_drive(dest)
    state = _load_state()
    custom = state.setdefault('custom_media', {'clips': [], 'audio': [], 'thumbnails': []})
    key = {'video': 'clips', 'audio': 'audio', 'thumbnail': 'thumbnails'}[media_type]
    custom[key] = [e for e in custom.get(key, []) if e.get('file_id') != file_id]
    custom[key].append({'path': dest, 'scope': scope, 'file_id': file_id})
    _save_state(state)
    scope_label = {'next': 'only in the next video', 'all': 'in all future videos'}.get(scope, f"in the video: '{scope[:60]}'")
    type_label = {'video': 'Video clips', 'audio': 'Audio', 'thumbnail': 'Thumbnail'}[media_type]
    await msg.reply_text(f"✅ {type_label} saved and will be used {scope_label}.\nPath: <code>{dest}</code>\n\nCaption: empty=next, 'all'=all videos, number=queued topic N.", parse_mode='HTML')

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if not text:
        return
    chat_id = str(update.message.chat_id)
    await update.message.chat.send_action('typing')
    loop = asyncio.get_event_loop()
    state = _load_state()
    history = _get_history(state, chat_id)
    if _is_preference_list_request(text):
        from moduli.preferenze import formato_html
        await update.message.reply_text(formato_html(), parse_mode='HTML')
        return
    from moduli.preferenze import aggiorna_da_testo
    pref_updates = aggiorna_da_testo(text)
    if pref_updates and (not any((k in text.lower() for k in _ACTION_KEYWORDS))):
        await update.message.reply_text(_format_preference_updates(pref_updates), parse_mode='HTML')
        return
    future = loop.run_in_executor(None, _ask_ai, text, history, state)
    while not future.done():
        await asyncio.sleep(4)
        if not future.done():
            await update.message.chat.send_action('typing')
    reply, new_history = await future
    state = _load_state()
    clean_reply, added_topics, saved_memories, removed_memories, api_results, deferred_tasks = _execute_actions(reply, state, is_search=_needs_web_search(text), is_pref_only=_is_pref_only_request(text))
    _save_history(state, chat_id, new_history)
    _save_state(state)
    had_actions = bool(deferred_tasks or api_results or added_topics or saved_memories or removed_memories)
    if clean_reply:
        msg = clean_reply
    elif had_actions:
        msg = None
    else:
        msg = reply or '⚠️ The AI model returned an empty response. Try again.'
    if msg:
        if len(msg) > 4096:
            for i in range(0, len(msg), 4096):
                await update.message.reply_text(msg[i:i + 4096])
        else:
            await update.message.reply_text(msg)
    if deferred_tasks:
        labels = {'thumbnail': '🖼 Generating the thumbnail…', 'audio': '🎙 Generating audio…', 'script': '📝 Writing the script…', 'video': '🎬 Loading the video…'}
        for tt, _p in deferred_tasks:
            await update.message.reply_text(labels.get(tt, '⏳ Working…'))
    if added_topics:
        elenco = '\n'.join((f'• {_h(t)}' for t in added_topics))
        await update.message.reply_text(f'✅ <b>Added {len(added_topics)} topics to the queue:</b>\n{elenco}', parse_mode='HTML')
    if saved_memories:
        elenco = '\n'.join((f'• {_h(m)}' for m in saved_memories))
        await update.message.reply_text(f'🧠 <b>Saved:</b>\n{elenco}', parse_mode='HTML')
    if removed_memories:
        elenco = '\n'.join((f'• {_h(m)}' for m in removed_memories))
        await update.message.reply_text(f'🗑 <b>Removed from memory:</b>\n{elenco}', parse_mode='HTML')
    for msg in api_results:
        await update.message.reply_text(msg, parse_mode='HTML')
    for task_type, payload in deferred_tasks:
        if task_type == 'thumbnail':
            await update.message.chat.send_action('upload_photo')
            preview_path = 'output/thumbnail_preview.jpg'
            try:
                from moduli.thumbnail import genera_thumbnail
                await loop.run_in_executor(None, lambda t=payload: genera_thumbnail(t, preview_path))
                with open(preview_path, 'rb') as f:
                    await update.message.reply_photo(f, caption=f'🖼 <b>{_h(payload)}</b>', parse_mode='HTML')
            except Exception as e:
                await update.message.reply_text(f'❌ Thumbnail error: {_h(str(e))}', parse_mode='HTML')
        elif task_type == 'audio':
            await update.message.chat.send_action('record_voice')
            audio_path = 'output/audio_preview.mp3'
            try:
                from moduli.audio import genera_audio
                await loop.run_in_executor(None, lambda t=payload: genera_audio(t, audio_path))
                with open(audio_path, 'rb') as f:
                    await update.message.reply_audio(f, title='Audio preview')
            except Exception as e:
                await update.message.reply_text(f'❌ Audio error: {_h(str(e))}', parse_mode='HTML')
        elif task_type == 'script':
            await update.message.chat.send_action('typing')
            try:
                from moduli.cervello import genera_contenuto
                from moduli.strategia import calcola_strategia

                def _gen_script(topic=payload):
                    strat = calcola_strategia([])
                    return genera_contenuto(topic, strategy=strat)
                content = await loop.run_in_executor(None, _gen_script)
                script_msg = f"📝 <b>{_h(content['title'])}</b>\n\n<b>Script ({len(content.get('script', '').split())} words):</b>\n{_h(content.get('script', '')[:3500])}"
                for i in range(0, len(script_msg), 4096):
                    await update.message.reply_text(script_msg[i:i + 4096], parse_mode='HTML')
                if content.get('description'):
                    desc_msg = f"<b>Description:</b>\n{_h(content['description'][:1000])}"
                    await update.message.reply_text(desc_msg, parse_mode='HTML')
                if content.get('tags'):
                    await update.message.reply_text(f"🏷 {_h(', '.join(content['tags']))}", parse_mode='HTML')
            except Exception as e:
                await update.message.reply_text(f'❌ Script error: {_h(str(e))}', parse_mode='HTML')
        elif task_type == 'video':
            video_path = 'output/output_finale.mp4'
            if os.path.exists(video_path):
                size_mb = os.path.getsize(video_path) / (1024 * 1024)
                if size_mb <= 50:
                    await update.message.chat.send_action('upload_video')
                    with open(video_path, 'rb') as f:
                        await update.message.reply_video(f, caption='🎬 Latest produced video')
                else:
                    fresh = _load_state()
                    video_ids = fresh.get('video_ids', [])
                    if video_ids:
                        await update.message.reply_text(f"📦 Video too large for Telegram ({size_mb:.0f} MB).\n🔗 <a href='https://youtu.be/{_h(video_ids[0])}'>Watch on YouTube</a>", parse_mode='HTML', disable_web_page_preview=False)
                    else:
                        await update.message.reply_text(f'📦 Video too large for Telegram ({size_mb:.0f} MB) and no video has been published yet.', parse_mode='HTML')
            else:
                await update.message.reply_text('❌ No video found at output/output_finale.mp4 — run the pipeline first.')

def start_bot() -> threading.Thread | None:
    """Start the bot in a daemon thread; return the thread or None without a token, allowing watchdog checks."""
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print('[Telegram] No token — bot disabled')
        return None

    async def _run():
        app = Application.builder().token(token).read_timeout(30).write_timeout(30).build()
        app.add_handler(CommandHandler('start', _authorized(cmd_start)))
        app.add_handler(CommandHandler('status', _authorized(cmd_status)))
        app.add_handler(CommandHandler('recap', _authorized(cmd_recap)))
        app.add_handler(CommandHandler('preferences', _authorized(cmd_preferenze)))
        app.add_handler(CommandHandler('setpref', _authorized(cmd_setpref)))
        app.add_handler(CommandHandler('run', _authorized(cmd_forza)))
        app.add_handler(CommandHandler('publishnow', _authorized(cmd_forzaora)))
        app.add_handler(CommandHandler('skip', _authorized(cmd_skip)))
        app.add_handler(CommandHandler('abort', _authorized(cmd_abort)))
        app.add_handler(CommandHandler('confirm', _authorized(cmd_conferma)))
        app.add_handler(CommandHandler('cancel', _authorized(cmd_annulla)))
        app.add_handler(CommandHandler('queue', _authorized(cmd_coda)))
        app.add_handler(CommandHandler('topic', _authorized(cmd_topic)))
        app.add_handler(CommandHandler('deltopic', _authorized(cmd_deltopic)))
        app.add_handler(CommandHandler('setvideosperday', _authorized(cmd_setvideogiorno)))
        app.add_handler(CommandHandler('autoscheduling', _authorized(cmd_autoscheduling)))
        app.add_handler(CommandHandler('schedule', _authorized(cmd_orari)))
        app.add_handler(CommandHandler('upcoming', _authorized(cmd_prossimi)))
        app.add_handler(CommandHandler('setpublish', _authorized(cmd_setpubblica)))
        app.add_handler(CommandHandler('channel', _authorized(cmd_canale)))
        app.add_handler(CommandHandler('setdesc', _authorized(cmd_setdesc)))
        app.add_handler(CommandHandler('video', _authorized(cmd_video)))
        app.add_handler(CommandHandler('playlist', _authorized(cmd_playlist)))
        app.add_handler(CommandHandler('newplaylist', _authorized(cmd_nuovaplaylist)))
        app.add_handler(CommandHandler('comments', _authorized(cmd_commenti)))
        app.add_handler(CommandHandler('reset', _authorized(cmd_reset)))
        app.add_handler(CommandHandler('memory', _authorized(cmd_memoria)))
        app.add_handler(CommandHandler('forget', _authorized(cmd_dimentica)))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _authorized(handle_message)))
        app.add_handler(MessageHandler(filters.VIDEO | filters.AUDIO | filters.VOICE | filters.PHOTO | filters.Document.VIDEO | filters.Document.AUDIO, _authorized(handle_media)))
        await app.initialize()
        await app.bot.set_my_commands([('start', 'Show all commands'), ('status', 'Current agent status'), ('recap', 'Recent video analytics'), ('run', 'Start the pipeline now'), ('publishnow', 'Publish immediately without scheduling'), ('skip', "Skip today's video"), ('abort', 'Stop the running pipeline'), ('confirm', 'Confirm an action'), ('cancel', 'Cancel an action'), ('schedule', 'Current schedule'), ('upcoming', 'Next production and publication'), ('setvideosperday', 'Set videos per day'), ('setpublish', 'Publication times (UTC)'), ('autoscheduling', 'Automatic times from analytics'), ('queue', 'Queued topics'), ('topic', 'Add a topic to the queue'), ('deltopic', 'Remove a queued topic'), ('channel', 'Channel information and statistics'), ('setdesc', 'Update channel description'), ('video', 'Recent published videos'), ('playlist', 'Channel playlists'), ('newplaylist', 'Create a playlist'), ('comments', 'Read video comments'), ('reset', 'Reset conversation context'), ('memory', 'Show long-term memory'), ('forget', 'Remove a memory')])
        _conflict_count = {'n': 0}

        async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
            from telegram.error import Conflict
            if isinstance(context.error, Conflict):
                _conflict_count['n'] += 1
                if _conflict_count['n'] == 1:
                    print('[Telegram] Conflict: another session is active or the connection is stale.\n           Waiting 60 seconds for expiry. If this persists, stop\n           tube-assistant processes on the other machines.', flush=True)
                elif _conflict_count['n'] >= 4:
                    print('\n[Telegram] FATAL: conflict persists after 4 attempts.\nStop the other instance (PC/server), then restart:\n  pkill -f tube-assistant   (on every machine)\n', flush=True)
                    os._exit(1)
                return
            print(f'[Telegram] Error: {context.error}', flush=True)
        app.add_error_handler(_on_error)
        from telegram.error import Conflict, NetworkError, TimedOut
        for tentativo in range(1, 7):
            try:
                await app.start()
                await app.updater.start_polling(drop_pending_updates=True, bootstrap_retries=-1)
                break
            except (Conflict, NetworkError, TimedOut) as e:
                wait = min(60, 5 * tentativo)
                tipo = type(e).__name__
                print(f'[Telegram] Bootstrap {tipo} (attempt {tentativo}/6). Retrying in {wait}s. If this persists, stop the other instances.', flush=True)
                try:
                    await app.updater.stop()
                except Exception:
                    pass
                try:
                    await app.stop()
                except Exception:
                    pass
                await asyncio.sleep(wait)
        else:
            print('\n[Telegram] FATAL: polling could not start after 6 attempts.\nStop the other instance (PC/server), then restart:\n  pkill -f tube-assistant   (on every machine)\n', flush=True)
            os._exit(1)
        print('[Telegram] Bot polling started')
        while True:
            await asyncio.sleep(30)
            updater = getattr(app, 'updater', None)
            if updater is not None and (not updater.running):
                print('[Telegram] Polling stopped — closing this thread so the watchdog can restart it', flush=True)
                break
        try:
            await app.updater.stop()
        except Exception:
            pass
        try:
            await app.stop()
            await app.shutdown()
        except Exception:
            pass

    def _thread():
        try:
            asyncio.run(_run())
        except Exception as e:
            print(f'[Telegram] Thread ended with an error: {type(e).__name__}: {e}', flush=True)
    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    return t
