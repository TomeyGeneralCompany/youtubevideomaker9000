import json
import os
import re
from datetime import datetime, timezone
from moduli.ai_client import chat_ollama
from moduli.preferenze import carica as carica_preferenze
HISTORY_FILE = 'strategia_storia.json'
DEFAULT_STRATEGY = {'topic_focus': 'AI and technology trends', 'title_style': 'curiosity-driven, slightly provocative', 'tone': 'confident and informative', 'hook_strength': 'medium', 'notes': 'No prior data. Use standard approach.'}
STRATEGY_PROMPT = 'You are a long-term YouTube growth strategist for a tech/AI channel.\n\nRecent video performance (newest first):\n{performance_json}\n\nTop performing videos (highest CTR × retention score):\n{top_performers}\n\nUnderperforming videos (lowest score):\n{underperformers}\n\nPrevious strategies tried (most recent first):\n{history_json}\n\nUser preferences (HARD CONSTRAINTS — never violate):\n{preferences}\n{metriche_nota}\n\nProduce an EVOLVED strategy that:\n- Learns from what\'s working and what isn\'t (CTR, retention, views)\n- Identifies TOPIC PATTERNS from top vs bottom performers (what subject matter, angle, framing worked?)\n- Avoids repeating failed title styles, tones, or topic angles\n- Doubles down on patterns that increased CTR or retention\n- Respects user preferences absolutely\n\nReply ONLY valid JSON:\n{{\n  "topic_focus": "specific topic areas/angles that showed best performance, or new territory to test if all underperformed",\n  "title_style": "concrete actionable title writing style based on what worked",\n  "tone": "narration tone",\n  "hook_strength": "soft | medium | aggressive",\n  "avoid_patterns": "specific title styles, tones, or topic angles that underperformed — avoid these",\n  "notes": "3-5 specific data-backed lessons from the performance data + concrete improvement plan"\n}}\n\nRules:\n- Avg CTR < 3%: bolder titles, stronger curiosity gap, more provocative hooks\n- Retention < 40%: harder opening hook, shorter sentences, faster pacing, cut dead intros\n- Views < 100 on 3+ videos in a row: pivot topic category entirely, not just title tweaks\n- If top performers share a topic pattern: that\'s the direction to pursue\n- If a past strategy led to measurable improvement: continue that trajectory\n- NEVER copy a previous strategy from the history word for word: this run must\n  produce new wording and at least one new, concrete decision. The history is\n  context to build on, not an answer to repeat.\n- Reply ONLY with JSON, no explanation outside JSON.\n'

def _load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_history(history: list) -> None:
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-20:], f, indent=2, ensure_ascii=False)

def _score_video(v: dict) -> float:
    views = float(v.get('views') or 0)
    ctr = float(v.get('ctr_percent') or 0)
    dur = max(float(v.get('duration_seconds') or 1), 1.0)
    retention = float(v.get('avg_view_duration_seconds') or 0) / dur * 100
    return views * 0.4 + ctr * 30 + retention * 2

def _analytics_mancanti(videos: list[dict]) -> bool:
    """Return whether Analytics metrics are unavailable for all videos. Avoid making strategy decisions from nonexistent zero values."""
    return bool(videos) and all((v.get('analytics_disponibili') is False for v in videos))

def _perf_snapshot(videos: list[dict], con_analytics: bool=True) -> list[dict]:
    snapshot = []
    for v in videos:
        riga = {'title': v.get('title', '')[:60], 'views': v.get('views', 0), 'likes': v.get('likes', 0), 'comments': v.get('comments', 0)}
        if con_analytics:
            riga['ctr_pct'] = round(float(v.get('ctr_percent') or 0), 2)
            riga['retention_pct'] = round(float(v.get('avg_view_duration_seconds') or 0) / max(float(v.get('duration_seconds') or 1), 1.0) * 100, 1)
        else:
            riga['ctr_pct'] = 'unavailable'
            riga['retention_pct'] = 'unavailable'
        riga['score'] = round(_score_video(v), 1)
        snapshot.append(riga)
    return snapshot

def calcola_strategia(performance: list[dict]) -> dict:
    pref = carica_preferenze()
    if not performance:
        return {**DEFAULT_STRATEGY, 'topic_focus': ', '.join(pref.get('preferred_topics', []))}
    history = _load_history()
    con_analytics = not _analytics_mancanti(performance)
    scored = sorted(performance, key=_score_video, reverse=True)
    top = _perf_snapshot(scored[:3], con_analytics)
    bottom = _perf_snapshot(scored[-3:], con_analytics) if len(scored) > 3 else []
    try:
        prompt = STRATEGY_PROMPT.format(performance_json=json.dumps(_perf_snapshot(performance, con_analytics), indent=2), top_performers=json.dumps(top, indent=2), underperformers=json.dumps(bottom, indent=2), history_json=json.dumps(history[-5:], indent=2) if history else '[]', preferences=json.dumps(pref, indent=2, ensure_ascii=False), metriche_nota='' if con_analytics else '\nIMPORTANT: CTR, impressions and retention are marked "unavailable" — the YouTube Analytics API is not enabled for this channel. Treat them as UNKNOWN, never as zero. Base your reasoning only on views, likes, comments and titles, and do not claim CTR or retention is low. Some strategies in the history below assert "zero CTR" or "0% retention": those claims came from the same missing data — do not repeat them.\n')
        text = chat_ollama(prompt, max_tokens=800)
        match = re.search('\\{.*\\}', text, re.DOTALL)
        if match:
            strategy = json.loads(match.group())
            history.append({'date': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'strategy': strategy, 'top_performers': top, 'underperformers': bottom})
            _save_history(history)
            return strategy
    except Exception as e:
        print(f'Strategy generation failed: {e}. Using default.')
    return DEFAULT_STRATEGY

def storia_strategia() -> list:
    return _load_history()
