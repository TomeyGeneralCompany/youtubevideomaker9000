import os
import time
import random
import threading
import requests
_sampling_ctx = threading.local()

def _temp(default: float=0.9) -> float:
    t = getattr(_sampling_ctx, 'temperature', None)
    return default if t is None else t

def _seed() -> int:
    s = getattr(_sampling_ctx, 'seed', None)
    return s if s is not None else random.randint(1, 2147483647)
AI_SERVICE = os.environ.get('AI_SERVICE', 'openrouter')
OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'meta-llama/llama-3.3-70b-instruct:free')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.8-flash')
OLLAMA_CLOUD_URL = 'https://ollama.com/api/chat'
OLLAMA_CLOUD_MODEL = os.environ.get('OLLAMA_CLOUD_MODEL', 'nemotron-3-super:cloud')
OLLAMA_LOCAL_URL = 'http://localhost:11434/api/chat'
OLLAMA_LOCAL_MODEL = os.environ.get('OLLAMA_LOCAL_MODEL', 'qwen3:4b')

def _openrouter(messages: list, max_tokens: int=4096) -> str:
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not api_key:
        raise RuntimeError('OPENROUTER_API_KEY missing in .env')
    for attempt in range(5):
        resp = requests.post(OPENROUTER_URL, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json', 'HTTP-Referer': 'tube-assistant'}, json={'model': OPENROUTER_MODEL, 'messages': messages, 'max_tokens': max_tokens, 'temperature': _temp(), 'seed': _seed()}, timeout=180)
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f'[OpenRouter] 429 — waiting {wait}s...', flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message'].get('content')
        if content:
            return content.strip()
        time.sleep(10 * (attempt + 1))
    raise RuntimeError('OpenRouter: empty content after retries')

def _gemini(messages: list, max_tokens: int=4096) -> str:
    from moduli.quota_control import check_cooldown
    check_cooldown()
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError('google-generativeai not installed. Run: pip install google-generativeai')
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        raise RuntimeError('GEMINI_API_KEY missing in .env')
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    history, prompt = ([], '')
    for m in messages:
        if m['role'] == 'system':
            history += [{'role': 'user', 'parts': [m['content']]}, {'role': 'model', 'parts': ['Understood.']}]
        elif m['role'] == 'user':
            prompt = m['content']
        elif m['role'] == 'assistant':
            history.append({'role': 'model', 'parts': [m['content']]})
    chat = model.start_chat(history=history)
    from moduli.shorts import retry

    def request():
        resp = chat.send_message(prompt, request_options={'timeout': 120}, generation_config={'max_output_tokens': max_tokens, 'temperature': _temp()})
        try:
            text = resp.text.strip()
        except (ValueError, AttributeError) as exc:
            raise RispostaVuota('Gemini returned no usable text; inspect finish reason/model settings') from exc
        if not text:
            raise RispostaVuota('Gemini returned empty text')
        return text
    return retry(request)

class RispostaVuota(RuntimeError):
    """The model returned reasoning without usable answer content."""
RITENTATIVI_OLLAMA = 2
FATTORE_BUDGET = 4

def _testo_ollama(payload: dict, modello: str) -> str:
    """Extract answer content from Ollama. Do not use the thinking field as narration; raise an error when the output budget was consumed by reasoning."""
    payload = payload or {}
    msg = payload.get('message', {}) or {}
    contenuto = (msg.get('content') or '').strip()
    if contenuto:
        return contenuto
    if (msg.get('thinking') or '').strip() or payload.get('done_reason') == 'length':
        raise RispostaVuota(f'{modello}: token budget exhausted during reasoning')
    raise RispostaVuota(f'{modello}: response has no content')

def _chat_ollama(url: str, modello: str, messages: list, max_tokens: int, headers: dict=None, think: bool=None) -> str:
    """Call Ollama with an expanded token budget on retry."""
    budget = max(1, max_tokens)
    ultimo = None
    for _ in range(RITENTATIVI_OLLAMA):
        corpo = {'model': modello, 'messages': messages, 'stream': False, 'options': {'num_predict': budget, 'temperature': _temp(), 'seed': _seed()}}
        if think is not None:
            corpo['think'] = think
        resp = requests.post(url, headers=headers, json=corpo, timeout=300)
        if resp.status_code == 404:
            raise RuntimeError(f"Ollama: model '{modello}' unavailable ({url}). Download it with: ollama pull {modello}")
        resp.raise_for_status()
        try:
            return _testo_ollama(resp.json(), modello)
        except RispostaVuota as e:
            print(f'[AI] {e} — retrying with num_predict {budget * FATTORE_BUDGET}', flush=True)
            ultimo = e
            budget *= FATTORE_BUDGET
    raise ultimo

def _ollama_cloud(messages: list, max_tokens: int=8192) -> str:
    api_key = os.environ.get('OLLAMA_API_KEY', '')
    modello = os.environ.get('OLLAMA_CLOUD_MODEL', OLLAMA_CLOUD_MODEL)
    return _chat_ollama(OLLAMA_CLOUD_URL, modello, messages, max_tokens, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, think=False)

def _ollama_local(messages: list, max_tokens: int = 8192) -> str:
    import re, json
    copied = [dict(m) for m in messages]
    if copied:
        copied[-1]['content'] += '\n/no_think'
    payload = {'model': 'qwen3:4b', 'messages': copied,
               'stream': False, 'think': False, 'keep_alive': 0,
               'options': {'num_ctx': 8192, 'num_predict': min(max_tokens, 4096),
                           'num_thread': 4, 'temperature': 0.6}}
    if copied and 'json' in copied[-1]['content'].lower():
        payload['format'] = 'json'
        prompt = copied[-1]['content']
        if 'closing_script' in prompt:
            strings = ['title', 'description', 'script', 'mood',
                       'thumbnail_phrase', 'closing_script']
            props = {key: {'type': 'string'} for key in strings}
            for key in ['tags', 'video_keywords']:
                props[key] = {'type': 'array', 'items': {'type': 'string'}}
            fact = {key: {'type': 'string'} for key in
                    ['source_id', 'claim', 'quote', 'value', 'period']}
            props['facts'] = {'type': 'array', 'items': {
                'type': 'object', 'properties': fact,
                'required': list(fact), 'additionalProperties': False}}
            payload['format'] = {'type': 'object', 'properties': props,
                                 'required': list(props), 'additionalProperties': False}
        elif '"script"' in prompt:
            payload['format'] = {'type': 'object',
                                 'properties': {'script': {'type': 'string'}},
                                 'required': ['script'], 'additionalProperties': False}
        if isinstance(payload['format'], dict):
            copied[-1]['content'] += '\nRequired JSON schema: ' + json.dumps(payload['format']) + '\n/no_think'
    print('[AI] Local Qwen3 writing; please allow several minutes.', flush=True)
    try:
        response = requests.post(OLLAMA_LOCAL_URL, json=payload, timeout=(10, 1800))
        response.raise_for_status()
        data = response.json()
        if data.get('done_reason') == 'length':
            raise RuntimeError('Local writer output truncated; rejected before narration')
        text = (data.get('message', {}).get('content') or '').strip()
        if '<think>' in text and '</think>' not in text:
            raise RuntimeError('Local writer returned incomplete thinking text')
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
        if not text:
            raise RuntimeError('Local writer returned no final answer')
        return text
    finally:
        try:
            requests.post('http://127.0.0.1:11434/api/generate',
                          json={'model': 'qwen3:4b', 'keep_alive': 0}, timeout=15)
        except Exception:
            pass
_PROVIDERS = {'openrouter': _openrouter, 'gemini': _gemini, 'ollama_cloud': _ollama_cloud, 'ollama_local': _ollama_local}

def _primary(messages: list, max_tokens: int=8192) -> str:
    svc = os.environ.get('AI_SERVICE', AI_SERVICE)
    fn = _PROVIDERS.get(svc)
    if fn is None:
        raise RuntimeError(f"Unknown AI_SERVICE '{svc}'. Valid: {', '.join(_PROVIDERS)}")
    cap = 4096 if svc not in ('ollama_cloud', 'ollama_local') else max_tokens
    return fn(messages, min(max_tokens, cap))

def _fallback(messages: list, max_tokens: int=4096) -> str:
    """Try fallback providers for which credentials are actually configured."""
    svc = os.environ.get('AI_SERVICE', AI_SERVICE)
    candidates = []
    if os.environ.get('PAUL_REVERE_FREE_ONLY', '0') != '1' and svc != 'openrouter' and os.environ.get('OPENROUTER_API_KEY', '').strip():
        candidates.append(('openrouter', _openrouter))
    if svc != 'ollama_local':
        candidates.append(('ollama_local', _ollama_local))
    last_err: Exception | None = None
    for name, fn in candidates:
        try:
            return fn(messages, min(max_tokens, 4096))
        except Exception as e:
            print(f'[AI] Fallback {name} failed: {e}', flush=True)
            last_err = e
    raise RuntimeError(f'All fallback AI providers failed: {last_err}')

def _non_vuota(testo: str) -> str:
    """Reject whitespace-only responses so fallback handling can proceed."""
    if not (testo or '').strip():
        raise RispostaVuota('empty response from the primary provider')
    return testo

def chat(prompt: str, system: str = None, max_tokens: int = 8192) -> str:
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    try:
        return _non_vuota(_primary(messages, max_tokens))
    except Exception as e:
        from moduli.quota_control import defer_if_daily_quota, QuotaPaused
        try:
            defer_if_daily_quota(e)
        except QuotaPaused:
            print('[AI] Gemini quota paused; using local Qwen3.', flush=True)
            return _non_vuota(_ollama_local(messages, max_tokens))
        print('[AI] Primary unavailable; trying fallback.', flush=True)
        return _non_vuota(_fallback(messages, max_tokens))

def chat_ollama(prompt: str, system: str=None, max_tokens: int=8192) -> str:
    return chat(prompt, system, max_tokens)
