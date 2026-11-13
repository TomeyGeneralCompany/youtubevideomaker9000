"""Read-only dashboard data from the scheduler and job checkpoints."""
from datetime import datetime, timedelta, timezone
import fcntl
import json
from statistics import median

STAGES = ('Setup', 'Script', 'Narration', 'Animation', 'Final render', 'Thumbnail', 'Upload', 'YouTube thumbnail')


def now_text():
    return datetime.now(timezone.utc).isoformat()


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _runner_busy(root):
    try:
        with (root / 'mavis.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except FileNotFoundError:
        pass
    return False


def overview(root, now=None):
    from run_mavis import config, slots
    now = now or datetime.now(timezone.utc)
    cfg = config(root)
    jobs = [(path.parent.name, _read(path)) for path in (root / 'runs').glob('*/checkpoint.json')]
    jobs.sort(key=lambda item: item[1].get('started_at') or '', reverse=True)
    busy = _runner_busy(root)
    active = next(((job, state) for job, state in jobs if state.get('started_at')
                   and not state.get('finished_at') and not state.get('error')), None) if busy else None
    history = [state for _, state in jobs if state.get('finished_at') and state.get('stage') == 'Complete'][:12]
    schedule = []
    if cfg['mode'] == 'scheduled':
        for slot in slots(cfg, now, upcoming=True):
            job = 'scheduled-' + slot.strftime('%Y%m%d-%H%M')
            if (not active or active[0] != job) and any(
                    key == job and (state.get('complete') or state.get('upload_started')) for key, state in jobs):
                continue
            start = slot - timedelta(minutes=int(cfg['lead_minutes']))
            schedule.append({'job': job, 'start': start.isoformat(), 'publish': slot.isoformat(),
                             'title': cfg.get('topic'), 'channel': cfg.get('expected_channel') or cfg.get('expected_channel_id'),
                             'status': 'Running' if active and active[0] == job else 'Due' if start <= now else 'Upcoming'})
            if len(schedule) == 5:
                break
    connected = _read(root / 'youtube-connection.json') if (root / 'token.json').is_file() else {}
    if ((cfg.get('expected_channel') and connected.get('channel') != cfg['expected_channel'])
            or (cfg.get('expected_channel_id') and connected.get('channel_id') != cfg['expected_channel_id'])):
        connected = {}
    current = None
    if active:
        job, state = active
        current = {'id': job, 'stage': state.get('stage'), 'start': state['started_at'],
                   'stage_start': state.get('stage_started_at'), 'publish': state.get('planned_publish_at'),
                   'title': (state.get('content') or {}).get('title') or state.get('job_title'),
                   'channel': (state.get('target_channel') or connected.get('channel') or cfg.get('expected_channel_id')) if state.get('upload_requested') else None, 'eta': None}
        stage = current['stage']
        if stage in STAGES:
            remaining = STAGES[STAGES.index(stage):]
            if not state.get('upload_requested'):
                remaining = tuple(name for name in remaining if name not in ('Upload', 'YouTube thumbnail'))
            samples = [sum(entry['stage_times'][name] for name in remaining)
                       for entry in history if all(name in entry.get('stage_times', {}) for name in remaining)]
            if samples and current['stage_start']:
                eta = datetime.fromisoformat(current['stage_start']) + timedelta(seconds=median(samples))
                if eta > now:
                    current['eta'] = eta.isoformat()
    return {'timezone': cfg['timezone'], 'mode': cfg['mode'], 'channel': cfg.get('expected_channel'),
            'channel_id': cfg.get('expected_channel_id'), 'connection': connected,
            'runner_busy': busy, 'schedule': schedule, 'active': current,
            'recent': [{'id': job, 'title': (state.get('content') or {}).get('title') or state.get('job_title'),
                        'stage': state.get('stage'), 'error': state.get('error'),
                        'finished': state.get('finished_at')} for job, state in jobs[:5]]}
