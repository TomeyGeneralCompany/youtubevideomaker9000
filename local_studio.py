"""Run the local production dashboard: python3 local_studio.py."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
import webbrowser

from moduli.shorts import atomic_json

SOURCE = Path(__file__).resolve().parent
JOB = re.compile(r'studio-[a-f0-9]{16}')


class Studio:
    def __init__(self, root):
        self.root = root
        self.runs = root / 'runs'
        self.lock = threading.Lock()
        self.process = None
        self.active = None

    def folder(self, job):
        if not JOB.fullmatch(job):
            raise ValueError('Invalid job.')
        folder = self.runs / job
        if folder.is_symlink() or not (folder / 'studio.json').is_file():
            raise ValueError('Unknown job.')
        return folder

    def start(self, data):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise ValueError('A local production job is already running.')
            job = data.get('resume')
            if job:
                folder = self.folder(job)
                if (folder / 'validation.json').exists() and (folder / 'short.mp4').exists():
                    raise ValueError('This job already has a finished video.')
                settings = json.loads((folder / 'studio.json').read_text())
            else:
                settings = {
                    'TUBE_OFFLINE': '0' if data.get('research') else '1',
                    'TUBE_CAPTIONS': '1' if data.get('captions') else '0',
                }
                for field, key in [('music', 'TUBE_MUSIC_FILE'), ('ffmpeg', 'FFMPEG_PATH'), ('ffprobe', 'FFPROBE_PATH')]:
                    value = str(data.get(field, '')).strip()
                    if value:
                        path = Path(value).expanduser()
                        path = (self.root / path).resolve()
                        if not path.is_file():
                            raise ValueError(f'{field}: file not found: {path}')
                        settings[key] = str(path)
                    elif field == 'music':
                        settings[key] = ''
                volume = float(data.get('volume', '0.1'))
                if not 0 <= volume <= 1:
                    raise ValueError('Music volume must be between 0 and 1.')
                settings['TUBE_MUSIC_VOLUME'] = str(volume)
                script = str(data.get('script', '')).strip()
                title = str(data.get('title', '')).strip()
                if script and not title:
                    raise ValueError('Enter a title for the supplied script.')
                job = 'studio-' + secrets.token_hex(8)
                folder = self.runs / job
                folder.mkdir(parents=True)
                if script:
                    atomic_json(folder / 'editorial.json', {'title': title, 'script': script})
                atomic_json(folder / 'studio.json', settings)
            env = {**os.environ, **settings, 'TUBE_WORKSPACE': str(self.root), 'PYTHONUNBUFFERED': '1'}
            cmd = [sys.executable, str(SOURCE / 'paul_revere.py'), 'run', '--job-id', job]
            if (folder / 'editorial.json').is_file():
                cmd.extend(['--script', str(folder / 'editorial.json')])
            with (folder / 'studio.log').open('ab') as log:
                self.process = subprocess.Popen(cmd, cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT)
            self.active = job
            return job

    def status(self, job):
        folder = self.folder(job)
        checkpoint = folder / 'checkpoint.json'
        state = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        with self.lock:
            running = self.active == job and self.process.poll() is None
        ready = (folder / 'validation.json').is_file() and (folder / 'short.mp4').is_file()
        log = folder / 'studio.log'
        output = ''
        if log.is_file():
            with log.open('rb') as stream:
                stream.seek(max(0, log.stat().st_size - 5000))
                output = stream.read().decode(errors='replace')
        return {'job': job, 'running': running, 'ready': ready, 'script': state.get('content', {}).get('script'),
                'stage': ('Preview' if ready else 'Render' if state.get('audio_done') else
                          'Narration' if state.get('content') else 'Script'), 'log': output}

    def setup(self):
        from moduli.ffmpeg_utils import ffmpeg_path, ffprobe_path
        from moduli.local_voice import BASE, CODEC, DESIGN, ENGINE, MODELS, profile
        from paul_revere_animation_guard import verify_approved_animation

        def check(fn, ok):
            try:
                return fn() or ok
            except Exception as exc:
                return str(exc)

        def voice():
            settings = profile()
            binary = ENGINE / 'source/build/qwen-tts'
            paths = [binary, MODELS / BASE, MODELS / CODEC]
            if settings.get('reference_wav'):
                paths.append(self.root / Path(settings['reference_wav']).expanduser())
            else:
                paths.append(MODELS / DESIGN)
            for path in paths:
                if not path.is_file():
                    return f'Missing {path}'
            return 'Ready' if os.access(binary, os.X_OK) else f'Cannot execute {binary}'

        def writer():
            try:
                with build_opener(ProxyHandler({})).open('http://127.0.0.1:11434/api/tags', timeout=2) as response:
                    models = json.load(response).get('models', [])
            except OSError:
                return 'Start Ollama to generate a script, or supply your own.'
            return ('Ready' if any(model.get('name') == 'qwen3:4b' for model in models)
                    else 'Install qwen3:4b in Ollama, or supply your own script.')

        return {'Workspace': str(self.root), 'FFmpeg': check(ffmpeg_path, 'Ready'),
                'FFprobe': check(ffprobe_path, 'Ready'), 'Local Qwen writer': check(writer, 'Ready'),
                'Local narration': check(voice, 'Ready'),
                'Animation': check(verify_approved_animation, 'Ready')}



def serve(studio, port):
    key = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def respond(self, status, content, mime):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)

        def json(self, status, data):
            self.respond(status, json.dumps(data).encode(), 'application/json')

        def do_GET(self):
            if not self.valid_host():
                return self.send_error(403)
            path = urlsplit(self.path).path
            if path == '/':
                page = (SOURCE / 'studio.html').read_text().replace('__STUDIO_TOKEN__', key)
                return self.respond(200, page.encode(), 'text/html; charset=utf-8')
            if path == '/setup':
                return self.json(200, studio.setup())
            match = re.fullmatch(r'/(status|video)/(studio-[a-f0-9]{16})', path)
            if not match:
                return self.send_error(404)
            mode, job = match.groups()
            try:
                state = studio.status(job)
                if mode == 'status':
                    return self.json(200, state)
                if state['ready']:
                    with (studio.folder(job) / 'short.mp4').open('rb') as video:
                        self.send_response(200)
                        self.send_header('Content-Type', 'video/mp4')
                        self.send_header('Content-Length', str(os.fstat(video.fileno()).st_size))
                        self.end_headers()
                        shutil.copyfileobj(video, self.wfile)
                    return
            except ValueError:
                pass
            self.send_error(404)

        def do_POST(self):
            if (not self.valid_host() or self.path != '/jobs'
                    or not hmac.compare_digest(self.headers.get('X-Studio-Token', ''), key)):
                return self.send_error(403)
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 100_000:
                    raise ValueError('Invalid job size.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Invalid job.')
                return self.json(200, {'job': studio.start(data)})
            except (ValueError, TypeError, OSError) as exc:
                self.json(400, {'error': str(exc)})

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    from paul_revere import ROOT, boot
    boot()
    with serve(Studio(ROOT), args.port) as server:
        url = f'http://127.0.0.1:{server.server_port}'
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        server.serve_forever()


if __name__ == '__main__':
    main()
