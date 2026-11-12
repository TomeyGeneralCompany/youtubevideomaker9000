import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_studio import Studio, serve
from mavis.model_json import decode_script
from mavis.shorts import atomic_json
from mavis import youtube_upload
from mavis.upload_metadata import prepare_upload_snippet


class StudioTests(unittest.TestCase):
    def test_browser_job_resumes_with_same_local_settings_and_previews(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = Studio(root)
            with serve(studio, 0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f'http://127.0.0.1:{server.server_port}'
                try:
                    with urlopen(base, timeout=5) as response:
                        page = response.read().decode()
                    token = re.search(r"'X-Studio-Token':'([^']+)'", page)[1]
                    def post(data, key=token):
                        req = Request(base + '/jobs', data=json.dumps(data).encode(),
                                      headers={'X-Studio-Token': key, 'Content-Type': 'application/json'})
                        with urlopen(req, timeout=5) as response:
                            return json.load(response)['job']
                    with self.assertRaises(HTTPError) as rejected:
                        post({}, key='wrong')
                    self.assertEqual(rejected.exception.code, 403)
                    process = Mock()
                    process.poll.return_value = None
                    with patch('local_studio.subprocess.Popen', return_value=process) as launch:
                        job = post({'title': 'Test', 'script': 'Test script', 'captions': 'on'})
                        self.assertNotIn('--upload-private', launch.call_args.args[0])
                        self.assertEqual(launch.call_args.kwargs['env']['TUBE_OFFLINE'], '1')
                        with self.assertRaises(HTTPError):
                            post({})
                        folder = studio.folder(job)
                        content = {'script': 'Test script', 'title': 'Model title', 'description': 'Model description',
                                   'tags': ['first tag', 'second'], 'language': 'en-us', 'thumbnail_phrase': 'Model cover'}
                        atomic_json(folder / 'checkpoint.json', {'audio_done': True, 'content': content})
                        process.poll.return_value = 1
                        self.assertEqual(post({'resume': job}), job)
                        self.assertEqual(launch.call_count, 2)
                        self.assertIn(str(folder / 'editorial.json'), launch.call_args.args[0])
                        with urlopen(base + '/status/' + job, timeout=5) as response:
                            state = json.load(response)
                        self.assertEqual(state['stage'], 'Render')
                        self.assertEqual(state['thumbnail_text'], 'Model cover')
                        self.assertEqual(state['metadata']['defaultLanguage'], 'en-US')
                        youtube = Mock()
                        youtube.videos.return_value.insert.return_value.next_chunk.return_value = (None, {'id': 'video-id'})
                        with patch.object(youtube_upload, 'MediaFileUpload'):
                            youtube_upload.prepare_video_transfer(youtube, 'video.mp4', content, immediate=True)
                        sent = youtube.videos.return_value.insert.call_args.kwargs['body']['snippet']
                        self.assertEqual(state['metadata'], sent)
                        atomic_json(folder / 'validation.json', {})
                        (folder / 'short.mp4').write_bytes(b'preview')
                        with urlopen(base + '/video/' + job, timeout=5) as response:
                            self.assertEqual(response.read(), b'preview')
                finally:
                    server.shutdown()
                    thread.join()

    def test_structured_reply_rejects_fragments_and_wrong_field_types(self):
        valid = dict.fromkeys(('title', 'description', 'script', 'mood', 'thumbnail_phrase', 'closing_script'), 'text')
        valid.update(tags=['tag'], facts=[])
        self.assertEqual(decode_script(json.dumps(valid)), valid)
        for reply in ('extra ' + json.dumps(valid), '{"title":', '[]', json.dumps({**valid, 'tags': [7]})):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                decode_script(reply)

    def test_metadata_limits_and_language_fallback(self):
        source = {'title': '<' + 'T' * 101 + '>', 'description': '€' * 2000,
                  'tags': ['two words', 'x' * 488, 'extra'], 'language': 'not a language'}
        with patch('mavis.preferences.load_preferences', return_value={'language': 'it'}):
            snippet = prepare_upload_snippet(source)
            self.assertEqual(snippet['defaultLanguage'], 'it')
            self.assertEqual(prepare_upload_snippet({'title': 'No language'})['defaultLanguage'], 'it')
        self.assertEqual(snippet['title'], 'T' * 100)
        self.assertEqual(len(snippet['description'].encode('utf-8')), 4998)
        self.assertEqual(snippet['tags'], ['two words', 'x' * 488])
        with self.assertRaises(ValueError):
            prepare_upload_snippet({'title': '<>'})
