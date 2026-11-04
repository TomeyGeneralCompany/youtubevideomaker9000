"""Shared calculation of production and publication times. Priority: analytics-selected times when enabled, manually configured times, then evenly spaced defaults. Explicit trigger_hours_utc overrides calculated production times."""
from datetime import datetime, timedelta, timezone
TRIGGER_LEAD_HOURS = 3
DEFAULT_VIDEOS_PER_DAY = 1
DEFAULT_TRIGGER_HOURS = [14]
DEFAULT_PUBLISH_HOURS = [20]
PUBLISH_SPREADS = {1: [20], 2: [14, 20], 3: [10, 15, 20], 4: [9, 13, 17, 21], 5: [8, 11, 14, 17, 20]}

def videos_per_day(state: dict) -> int:
    try:
        return max(1, int(state.get('videos_per_day', DEFAULT_VIDEOS_PER_DAY)))
    except (TypeError, ValueError):
        return DEFAULT_VIDEOS_PER_DAY

def _ore_valide(hours) -> list[int]:
    """Discard nonnumeric hours and values outside the valid range."""
    valide = []
    for h in hours or ():
        try:
            h = int(h)
        except (TypeError, ValueError):
            continue
        if 0 <= h <= 23:
            valide.append(h)
    return valide

def publish_hours(state: dict) -> list[int]:
    """Return sorted UTC publication hours, limited to videos_per_day."""
    n = videos_per_day(state)
    hours = []
    if state.get('auto_scheduling'):
        hours = _ore_valide(state.get('best_hours_utc'))
    if not hours:
        hours = _ore_valide(state.get('publish_hours_utc'))
    if not hours:
        hours = PUBLISH_SPREADS.get(n, DEFAULT_PUBLISH_HOURS)
    return sorted(dict.fromkeys(hours))[:n]

def trigger_hours(state: dict) -> list[int]:
    """Return UTC production hours. Explicit trigger_hours_utc takes precedence over publication times minus the production lead."""
    n = videos_per_day(state)
    espliciti = _ore_valide(state.get('trigger_hours_utc'))
    if espliciti:
        return sorted(dict.fromkeys(espliciti))[:n]
    non_configurato = (not state.get('auto_scheduling') or not _ore_valide(state.get('best_hours_utc'))) and (not _ore_valide(state.get('publish_hours_utc')))
    if non_configurato and n == 1:
        return sorted(DEFAULT_TRIGGER_HOURS)[:n]
    return sorted(((h - TRIGGER_LEAD_HOURS) % 24 for h in publish_hours(state)))[:n]

def prossima_pubblicazione(state: dict, run_index: int=0, now: datetime | None=None) -> datetime:
    """Return the publication datetime for the requested video of the day."""
    now = now or datetime.now(timezone.utc)
    hours = publish_hours(state)
    hour = hours[run_index % len(hours)]
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate
