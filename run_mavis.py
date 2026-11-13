"""Run MAVIS production jobs, private tests, and scheduled publishing."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(os.environ.get('TUBE_WORKSPACE', Path.home() / '.tomey-media')).expanduser().resolve()

def boot():
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')

def config(root=None):
    defaults = {'timezone': 'America/Detroit', 'publish_times': ['18:00'], 'lead_minutes': 180, 'mode': 'private', 'expected_channel': None, 'topic': ''}
    file = (ROOT if root is None else root) / 'mavis.json'
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

def slots(cfg, now=None, *, upcoming=False):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(cfg['timezone']))
    answer = []
    for offset in range(8 if upcoming else 2):
        day = local.date() + timedelta(days=offset)
        for clock in sorted(set(cfg['publish_times'])):
            naive = datetime.combine(day, datetime.strptime(clock, '%H:%M').time())
            local_slot = naive.replace(tzinfo=ZoneInfo(cfg['timezone']))
            slot = local_slot.astimezone(timezone.utc)
            if slot.astimezone(local_slot.tzinfo).replace(tzinfo=None) != naive:
                continue
            start = slot - timedelta(minutes=int(cfg['lead_minutes']))
            if (now < slot if upcoming else start <= now < slot):
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
    data.setdefault('topic', data['title'])
    data.setdefault('description', data['title'] + ' #Shorts')
    data.setdefault('tags', [])
    data.setdefault('mood', 'epic')
    return data

def youtube_session(cfg, *, authorize=False):
    from mavis.google_auth import connect_youtube
    if not cfg.get('expected_channel') and not cfg.get('expected_channel_id'):
        raise ValueError('Set expected_channel or expected_channel_id in mavis.json before connecting YouTube.')

    verified_title = None

    def check_channel(client):
        nonlocal verified_title
        channels = client.channels().list(part='snippet', mine=True).execute(num_retries=5).get('items', [])
        if len(channels) != 1:
            raise RuntimeError('OAuth did not resolve exactly one channel')
        selected = channels[0]
        expected_id = cfg.get('expected_channel_id')
        expected_title = cfg.get('expected_channel')
        if (expected_title and selected['snippet']['title'] != expected_title) or (expected_id and selected['id'] != expected_id):
            raise RuntimeError('Connected YouTube channel does not match the configured channel')
        verified_title = selected['snippet']['title']
        return selected['id']

    client, channel_id = connect_youtube(ROOT, check_channel, authorize=authorize)
    from mavis.shorts import atomic_json
    atomic_json(ROOT / 'youtube-connection.json', {
        'channel_id': channel_id, 'channel': verified_title,
        'verified_at': datetime.now(timezone.utc).isoformat(),
    })
    return client, channel_id

def produce(job, cfg, editorial=None, upload=False, publish_at=None, self_test=False, topic=None):
    from mavis.subscription import require
    require(ROOT)
    from mavis.shorts import atomic_json, retry, validate_short
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
    from mavis.production_status import now_text
    state.pop('error', None)
    state.update(started_at=now_text(), stage=None, finished_at=None, stage_times={},
                 job_title=topic or cfg.get('topic'), target_channel=cfg.get('expected_channel'),
                 upload_requested=upload,
                 planned_publish_at=publish_at.isoformat() if publish_at else None)
    from time import monotonic
    stage_clock = monotonic()

    def stage(name):
        nonlocal stage_clock
        if state['stage']:
            state['stage_times'][state['stage']] = round(monotonic() - stage_clock, 2)
        state['stage'] = name
        state['stage_started_at'] = now_text()
        stage_clock = monotonic()
        atomic_json(state_path, state)

    try:
        stage('Setup')
        from mavis.animation_guard import verify_approved_animation
        verify_approved_animation()
        from mavis.ffmpeg_utils import ffmpeg_path, ffprobe_path
        ffmpeg_path()
        ffprobe_path()
        if 'content' not in state:
            stage('Script')
            if self_test:
                content = json.loads((ROOT / 'assets/animation/demo.json').read_text())
            elif editorial:
                content = read_editorial(editorial)
            else:
                from mavis.media_research import collect_evidence, write_mascot_content
                topic = (topic or cfg.get('topic') or '').strip()
                if not topic:
                    raise ValueError('Enter a topic or provide a script.')
                packet = {'sources': []} if os.getenv('TUBE_OFFLINE') == '1' else collect_evidence()
                atomic_json(directory / 'research.json', packet)
                content = write_mascot_content(topic, packet)
                content['topic'] = content['title']
            state['content'] = content
            atomic_json(state_path, state)
        content = state['content']
        audio = directory / ('narration.mp3' if self_test else 'narration.wav')
        legacy_audio = directory / 'narration.mp3'
        if not audio.exists() and state.get('audio_done') and legacy_audio.exists():
            audio = legacy_audio
        if state.get('audio_version') != 'mascot-ready-v4':
            state['audio_done'] = False
        if not state.get('audio_done') or not audio.exists():
            stage('Narration')
            if self_test:
                import shutil
                shutil.copyfile(ROOT / 'assets/animation/demo-narration.mp3', audio)
            else:
                from mavis.mascot import generate_host_audio
                retry(lambda: generate_host_audio(content, str(audio)))
            state['audio_done'] = True
            state['audio_version'] = 'mascot-ready-v4'
            atomic_json(state_path, state)
        os.environ['MAVIS_CURRENT_TITLE'] = content['title']
        os.environ['MAVIS_CLOSING_WORDS'] = str(len(content.get('closing_script', '').split()) or 35)
        video = directory / 'short.mp4'
        if state.get('renderer_version') != 'mascot-approved-cels-20261015-r1':
            state['render_done'] = False
        if not state.get('render_done') or not video.exists():
            from mavis.shorts import render_short
            stage('Animation')
            info = render_short(str(audio), str(video), custom_music=os.getenv('TUBE_MUSIC_FILE'), on_stage=stage, captions_text=content['script'] if os.getenv('TUBE_CAPTIONS', '1') == '1' else None)
            state['render_done'] = True
            state['renderer_version'] = 'mascot-approved-cels-20261015-r1'
            atomic_json(state_path, state)
        else:
            stage('Validation')
            info = validate_short(video)
        atomic_json(directory / 'validation.json', info)
        thumbnail = directory / 'thumbnail.jpg'
        if not thumbnail.exists() or state.get('cover_version') != 'mascot-approved-cels-20261015-r1':
            stage('Thumbnail')
            from mavis.mascot import mascot_cover
            mascot_cover(content.get('thumbnail_phrase') or content['title'], str(thumbnail))
            state['cover_version'] = 'mascot-approved-cels-20261015-r1'
            atomic_json(state_path, state)
        if self_test:
            atomic_json(ROOT / 'shorts-validated.json', {'job': job, 'validated_at': datetime.now(timezone.utc).isoformat()})
        if upload:
            stage('Upload')
            from mavis.youtube_upload import prepare_video_transfer, transfer_video, upload_thumbnail

            client, channel_id = retry(lambda: youtube_session(cfg))
            state['channel_id'] = channel_id
            if publish_at and publish_at <= datetime.now(timezone.utc):
                raise RuntimeError('Rendering missed the publication deadline; upload deferred')
            request = prepare_video_transfer(client, str(video), content, publish_at=publish_at,
                                             immediate=publish_at is None)
            state['upload_started'] = True
            atomic_json(state_path, state)
            video_id = transfer_video(request)
            state.update(video_id=video_id, publish_at=publish_at.isoformat() if publish_at else None, complete=True)
            atomic_json(state_path, state)
            print(f'Upload complete: https://youtu.be/{video_id}')
            try:
                stage('YouTube thumbnail')
                upload_thumbnail(client, video_id, str(thumbnail))
            except Exception as exc:
                print(f'Video saved; thumbnail upload failed: {exc}')
        state['complete'] = True
        state.pop('error', None)
        state['finished_at'] = now_text()
        stage('Complete')
        print('Completed:', video)
    except Exception as exc:
        state['error'] = f'{type(exc).__name__}: {exc}'
        state['finished_at'] = now_text()
        atomic_json(state_path, state)
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--script')
    run.add_argument('--topic')
    run.add_argument('--upload-private', action='store_true')
    run.add_argument('--job-id')
    test = sub.add_parser('self-test')
    test.add_argument('--upload-private', action='store_true')
    sub.add_parser('tick')
    sub.add_parser('authorize', help='Connect the configured YouTube channel in a browser')
    sub.add_parser('enable-scheduling')
    rec = sub.add_parser('reconcile')
    rec.add_argument('job')
    rec.add_argument('--video-id')
    rec.add_argument('--retry-upload', action='store_true')
    args = parser.parse_args()
    boot()
    from mavis.shorts import atomic_json
    cfg = config()
    with open(ROOT / 'mavis.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another MAVIS job is running')
            return
        if args.command == 'authorize':
            _, channel_id = youtube_session(cfg, authorize=True)
            print('Connected YouTube channel:', channel_id)
            return
        if args.command == 'enable-scheduling':
            if not (ROOT / 'shorts-validated.json').exists():
                raise RuntimeError('Run self-test successfully before enabling scheduling')
            _, cfg['expected_channel_id'] = youtube_session(cfg)
            private_test = False
            for checkpoint in (ROOT / 'runs').glob('*/checkpoint.json'):
                state = json.loads(checkpoint.read_text())
                if state.get('video_id') and state.get('channel_id') == cfg['expected_channel_id'] and (state.get('renderer_version') == 'mascot-approved-cels-20261015-r1') and (not state.get('publish_at')):
                    private_test = True
            if not private_test:
                raise RuntimeError('Complete a successful --upload-private test before enabling public scheduling')
            timer = cfg.get('scheduler_timer')
            if not isinstance(timer, str) or not timer.endswith('.timer') or not timer[0].isalnum() or '/' in timer:
                raise ValueError('Set scheduler_timer in mavis.json to your installed systemd user timer.')
            import subprocess
            subprocess.run(['systemctl', '--user', 'enable', timer], check=True)
            cfg['mode'] = 'scheduled'
            atomic_json(ROOT / 'mavis.json', cfg)
            subprocess.run(['systemctl', '--user', 'start', timer], check=True)
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
                client, channel_id = youtube_session(cfg)
                item = client.videos().list(part='snippet', id=args.video_id).execute(num_retries=5).get('items', [])
                if not item or item[0]['snippet']['channelId'] != channel_id:
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
            produce(job, cfg, args.script, args.upload_private, topic=args.topic)
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
            from mavis.subscription import require
            require(ROOT)
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
