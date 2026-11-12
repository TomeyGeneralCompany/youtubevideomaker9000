"""Generate scripts through the local Qwen model in Ollama."""
import requests

OLLAMA_LOCAL_URL = "http://localhost:11434/api/chat"


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
                       'thumbnail_phrase', 'closing_script', 'language']
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


def chat_ollama(prompt: str, system: str | None = None, max_tokens: int = 8192) -> str:
    turns = [('system', system), ('user', prompt)] if system else [('user', prompt)]
    return _ollama_local([dict(role=role, content=value) for role, value in turns], max_tokens)
