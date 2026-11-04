"""Stop daily-quota retry storms; persist provider cooldown across timer runs."""
import json, re, time, os
from pathlib import Path

class QuotaPaused(RuntimeError):
    pass

def cache_path():
    return Path(os.environ.get('TUBE_WORKSPACE', os.getcwd())) / 'cache/gemini-cooldown.json'

def check_cooldown():
    p = cache_path()
    if p.exists():
        try:
            until = float(json.loads(p.read_text())['until'])
        except (ValueError, KeyError, TypeError):
            return
        if until > time.time():
            raise QuotaPaused(f"Gemini daily quota cooldown: retry after {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until))}. Editorial scripts and offline self-test still work.")

def defer_if_daily_quota(exc):
    if isinstance(exc, QuotaPaused):
        raise exc
    message = str(exc)
    lower = message.lower()
    if not ('quota' in lower and ('requestsperday' in lower or 'requests_per_day' in lower or 'perdayperproject' in lower)):
        return
    match = re.search('seconds:\\s*(\\d+)', message)
    delay = int(match.group(1)) if match else 86400
    until = time.time() + max(60, delay) + 60
    from moduli.shorts import atomic_json
    atomic_json(cache_path(), {'until': until, 'reason': 'daily Gemini quota exhausted'})
    raise QuotaPaused(f"Gemini daily quota exhausted. Retry after {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(until))}; repeated retries stopped. Use your own script to continue.") from exc
