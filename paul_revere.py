"""One-shot, private test, and unattended jobs for the installed TubeAssistant."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
ROOT = Path(os.environ.get('TUBE_WORKSPACE', Path.home() / '.tomey-media')).expanduser().resolve()

def boot():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    os.environ.update(VIDEO_WIDTH='1080', VIDEO_HEIGHT='1920', VIDEO_FPS='30', VIDEO_SOURCE='ai', VIDEO_AI_PROVIDER='pollinations', IMAGE_PROVIDER='pollinations', VIDEO_CODEC='libx264', PAUL_REVERE_FREE_ONLY='1', PAUL_REVERE_PUBLISH_MODE='private', PAUL_REVERE_VIDEO_MODE='mascot')

def config():
    defaults = {'timezone': 'America/Detroit', 'publish_times': ['18:00'], 'lead_minutes': 180, 'mode': 'private', 'expected_channel': 'Paul Revere Media'}
    file = ROOT / 'paul_revere.json'
    if file.exists():
        defaults.update(json.loads(file.read_text()))
    if defaults['mode'] not in ('private', 'scheduled'):
        raise ValueError('mode must be private or scheduled')
    if not 5 <= int(defaults['lead_minutes']) <= 1440:
        raise ValueError('lead_minutes must be between 5 and 1440')
    ZoneInfo(defaults['timezone'])
    for value in defaults['publish_times']:
        datetime.strptime(value, '%H:%M')
    if not defaults['publish_times']:
        raise ValueError('At least one publication time is required')
    return defaults

def slots(cfg, now=None):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(cfg['timezone']))
    answer = []
    for offset in (0, 1):
        day = local.date() + timedelta(days=offset)
        for clock in sorted(set(cfg['publish_times'])):
            naive = datetime.combine(day, datetime.strptime(clock, '%H:%M').time())
            local_slot = naive.replace(tzinfo=ZoneInfo(cfg['timezone']))
            slot = local_slot.astimezone(timezone.utc)
            if slot.astimezone(local_slot.tzinfo).replace(tzinfo=None) != naive:
                continue
            if slot - timedelta(minutes=int(cfg['lead_minutes'])) <= now < slot:
                answer.append(slot)
    return answer

def read_editorial(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('script'), str) or (not data['script'].strip()):
        raise ValueError('Editorial JSON needs a nonempty script string')
    if not isinstance(data.get('title'), str) or not data['title'].strip():
        raise ValueError('Editorial JSON needs a title string')
    closing = data.get('closing_script', '')
    if not isinstance(closing, str) or (closing.strip() and (not data['script'].rstrip().endswith(closing.strip()))):
        raise ValueError('closing_script must be the exact ending of script')
    if closing.strip() and (not 28 <= len(closing.split()) <= 42):
        raise ValueError('closing_script must contain 28–42 words')
    text = ' '.join([data['title'], data.get('topic', ''), data['script']])
    import re
    if not re.search('\\b(trump|maga)\\b', text, re.I):
        raise ValueError('Paul Revere jobs must concern Trump or MAGA')
    data.setdefault('topic', data['title'])
    data.setdefault('description', data['title'] + ' #Shorts')
    data.setdefault('tags', ['Trump', 'MAGA', 'Paul Revere Media', 'Shorts'])
    data.setdefault('mood', 'epic')
    data.setdefault('video_keywords', ['American flags MAGA rally', 'Trump rally patriotic crowd', 'Americana dramatic golden light'])
    return data

def verify_channel(cfg):
    from google.oauth2.credentials import Credentials
    token = ROOT / 'token.json'
    if not token.exists():
        raise RuntimeError('Existing token.json is missing; complete the normal TubeAssistant OAuth login first')
    creds = Credentials.from_authorized_user_file(str(token))
    if not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError('OAuth token cannot refresh; use the existing interactive login')
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise RuntimeError('OAuth refresh failed; use the existing interactive TubeAssistant login') from exc
        token.write_text(creds.to_json(), encoding='utf-8')
        token.chmod(384)
    from moduli.pubblica import _get_youtube
    response = _get_youtube().channels().list(part='snippet', mine=True).execute(num_retries=5)
    items = response.get('items', [])
    if len(items) != 1:
        raise RuntimeError('OAuth did not resolve exactly one channel')
    channel = items[0]
    expected_id = cfg.get('expected_channel_id')
    if expected_id and channel['id'] != expected_id or channel['snippet']['title'] != cfg['expected_channel']:
        raise RuntimeError('Connected YouTube channel does not match Paul Revere Media configuration')
    return channel['id']

def produce(job, cfg, editorial=None, upload=False, publish_at=None, self_test=False):
    from paul_revere_animation_guard import verify_approved_animation
    verify_approved_animation()
    from moduli.shorts import atomic_json, retry, validate_short, probe
    directory = ROOT / 'runs' / job
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / 'checkpoint.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get('video_id'):
        if self_test:
            validate_short(directory / 'short.mp4')
            atomic_json(ROOT / 'shorts-validated.json', {'job': job, 'validated_at': datetime.now(timezone.utc).isoformat()})
        print('Already uploaded:', state['video_id'])
        return
    if state.get('upload_started'):
        raise RuntimeError(f'Upload outcome uncertain for {job}. Check YouTube Studio, then use reconcile. Automatic re-upload is blocked to avoid duplicates.')
    try:
        if 'content' not in state:
            if self_test:
                content = json.loads((ROOT / 'assets/animation/demo.json').read_text())
            elif editorial:
                content = read_editorial(editorial)
            else:
                from moduli.media_research import collect_evidence, write_mascot_content
                packet = collect_evidence()
                atomic_json(directory / 'research.json', packet)
                topic = 'Trump and MAGA accomplishments, patriotic celebration and supporter culture'
                content = retry(lambda: write_mascot_content(topic, packet))
                content['topic'] = content['title']
            state['content'] = content
            atomic_json(state_path, state)
        from paul_revere_metadata import enrich
        state['content'] = enrich(state['content'])
        atomic_json(state_path, state)
        content = state['content']
        audio = directory / 'narration.mp3'
        if state.get('audio_version') != 'mascot-ready-v4':
            state['audio_done'] = False
        if not state.get('audio_done') or not audio.exists():
            if self_test:
                import shutil
                shutil.copyfile(ROOT / 'assets/animation/demo-narration.mp3', audio)
            else:
                from moduli.mascot import generate_host_audio
                retry(lambda: generate_host_audio(content, str(audio)))
            state['audio_done'] = True
            state['audio_version'] = 'mascot-ready-v4'
            atomic_json(state_path, state)
        state['clips'] = {}
        atomic_json(state_path, state)
        os.environ['PAUL_REVERE_CURRENT_TITLE'] = content['title']
        os.environ['PAUL_REVERE_CLOSING_WORDS'] = str(len(content.get('closing_script', '').split()) or 35)
        video = directory / 'short.mp4'
        if state.get('renderer_version') != 'mascot-approved-cels-20261015-r1':
            state['render_done'] = False
        if not state.get('render_done') or not video.exists():
            from moduli.montaggio import monta_video
            monta_video(str(audio), list(state['clips']), state['clips'], str(video), mood=content.get('mood', 'epic'), captions_text=content['script'])
            state['render_done'] = True
            state['renderer_version'] = 'mascot-approved-cels-20261015-r1'
            atomic_json(state_path, state)
        info = validate_short(video)
        atomic_json(directory / 'validation.json', info)
        from moduli.mascot import write_host_srt
        write_host_srt(content['script'], str(directory / 'captions.srt'), closing_words=int(os.environ['PAUL_REVERE_CLOSING_WORDS']))
        thumbnail = directory / 'thumbnail.jpg'
        if not thumbnail.exists() or state.get('cover_version') != 'mascot-approved-cels-20261015-r1':
            from moduli.mascot import mascot_cover
            mascot_cover(content.get('thumbnail_phrase') or content['title'], str(thumbnail))
            state['cover_version'] = 'mascot-approved-cels-20261015-r1'
            atomic_json(state_path, state)
        if self_test:
            atomic_json(ROOT / 'shorts-validated.json', {'job': job, 'validated_at': datetime.now(timezone.utc).isoformat()})
        if upload:
            channel_id = retry(lambda: verify_channel(cfg))
            state['channel_id'] = channel_id
            if publish_at and publish_at <= datetime.now(timezone.utc):
                raise RuntimeError('Rendering missed the publication deadline; upload deferred')
            state['upload_started'] = True
            atomic_json(state_path, state)
            from moduli.pubblica import pubblica_video
            os.environ['PAUL_REVERE_PUBLISH_MODE'] = 'scheduled' if publish_at else 'private'

            def record_upload(video_id):
                state['video_id'] = video_id
                state['publish_at'] = publish_at.isoformat() if publish_at else None
                state['complete'] = True
                atomic_json(state_path, state)
            video_id = pubblica_video(str(video), str(thumbnail), content, publish_at=publish_at, immediate=publish_at is None, privacy_status='private', on_uploaded=record_upload)
            state['video_id'] = video_id
            state['publish_at'] = publish_at.isoformat() if publish_at else None
            atomic_json(state_path, state)
        state['complete'] = True
        state.pop('error', None)
        atomic_json(state_path, state)
        print('Completed:', video)
    except Exception as exc:
        state['error'] = f'{type(exc).__name__}: {exc}'
        atomic_json(state_path, state)
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--script')
    run.add_argument('--upload-private', action='store_true')
    run.add_argument('--job-id')
    test = sub.add_parser('self-test')
    test.add_argument('--upload-private', action='store_true')
    sub.add_parser('tick')
    sub.add_parser('enable-scheduling')
    rec = sub.add_parser('reconcile')
    rec.add_argument('job')
    rec.add_argument('--video-id')
    rec.add_argument('--retry-upload', action='store_true')
    args = parser.parse_args()
    boot()
    from moduli.shorts import atomic_json
    cfg = config()
    with open(ROOT / 'paul-revere.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another Paul Revere job is running')
            return
        if args.command == 'enable-scheduling':
            if not (ROOT / 'shorts-validated.json').exists():
                raise RuntimeError('Run self-test successfully before enabling scheduling')
            cfg['expected_channel_id'] = verify_channel(cfg)
            private_test = False
            for checkpoint in (ROOT / 'runs').glob('*/checkpoint.json'):
                state = json.loads(checkpoint.read_text())
                if state.get('video_id') and state.get('channel_id') == cfg['expected_channel_id'] and (state.get('renderer_version') == 'mascot-approved-cels-20261015-r1') and (not state.get('publish_at')):
                    private_test = True
            if not private_test:
                raise RuntimeError('Complete a successful --upload-private test before enabling public scheduling')
            cfg['mode'] = 'scheduled'
            atomic_json(ROOT / 'paul_revere.json', cfg)
            import subprocess
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'paul-revere-shorts.timer'], check=True)
            print('Scheduled publishing enabled for', cfg['publish_times'], cfg['timezone'])
            return
        if args.command == 'reconcile':
            if Path(args.job).name != args.job or args.job in ('.', '..'):
                raise ValueError('Invalid job ID')
            path = ROOT / 'runs' / args.job / 'checkpoint.json'
            state = json.loads(path.read_text())
            if bool(args.video_id) == bool(args.retry_upload):
                raise ValueError('Choose --video-id ID or --retry-upload after checking YouTube Studio')
            if args.video_id:
                verify_channel(cfg)
                from moduli.pubblica import _get_youtube
                item = _get_youtube().videos().list(part='snippet', id=args.video_id).execute().get('items', [])
                if not item or item[0]['snippet']['channelId'] != verify_channel(cfg):
                    raise ValueError('Video ID does not belong to the configured channel')
                state['video_id'] = args.video_id
                state['complete'] = True
            else:
                state.pop('upload_started', None)
            atomic_json(path, state)
            return
        if args.command == 'self-test':
            produce('mascot-complete-self-test', cfg, upload=args.upload_private, self_test=True)
            return
        if args.command == 'run':
            job = args.job_id or datetime.now(timezone.utc).strftime('mascot-manual-%Y%m%d-%H%M%S')
            if Path(job).name != job or job in ('.', '..'):
                raise ValueError('Invalid job ID')
            produce(job, cfg, args.script, args.upload_private)
            return
        if cfg['mode'] != 'scheduled':
            print('Scheduling is private/inactive; run enable-scheduling after testing')
            return
        if not (ROOT / 'shorts-validated.json').exists():
            raise RuntimeError('Missing successful self-test marker')
        for slot in slots(cfg):
            job = 'scheduled-' + slot.strftime('%Y%m%d-%H%M')
            checkpoint = ROOT / 'runs' / job / 'checkpoint.json'
            if checkpoint.exists() and json.loads(checkpoint.read_text()).get('complete'):
                continue
            job_path = ROOT / 'runs' / job
            job_path.mkdir(parents=True, exist_ok=True)
            source = job_path / 'editorial.json'
            if not source.exists() and (not checkpoint.exists()):
                queue = sorted((ROOT / 'scripts/queue').glob('*.json'))
                if queue:
                    os.replace(queue[0], source)
            produce(job, cfg, str(source) if source.exists() else None, upload=True, publish_at=slot)
if __name__ == '__main__':
    main()
