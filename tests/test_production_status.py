from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from mavis.production_status import overview


class ProductionStatusTests(unittest.TestCase):
    def test_schedule_active_stage_eta_and_verified_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def save(path, value):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value))

            save('mavis.json', {'mode': 'scheduled', 'timezone': 'America/Detroit',
                                'publish_times': ['18:00'], 'expected_channel': 'Garden Studio'})
            save('token.json', {})
            save('youtube-connection.json', {'channel': 'Garden Studio', 'channel_id': 'garden'})
            stamp = '2026-11-12T21:00:00+00:00'
            save('runs/scheduled-20261112-2300/checkpoint.json', {
                'started_at': stamp, 'stage_started_at': stamp, 'stage': 'Upload',
                'upload_requested': True, 'upload_started': True, 'job_title': 'Garden tips',
            })
            save('runs/prior/checkpoint.json', {
                'started_at': '2026-11-11T21:00:00+00:00', 'finished_at': stamp,
                'stage': 'Complete', 'stage_times': {'Upload': 65, 'YouTube thumbnail': 5},
            })
            now = datetime.fromisoformat(stamp)
            with (root / 'mavis.lock').open('wb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = overview(root, now)
            self.assertEqual(result['active']['stage'], 'Upload')
            self.assertEqual(result['active']['eta'], '2026-11-12T21:01:10+00:00')
            self.assertEqual(result['schedule'][0]['status'], 'Running')
            self.assertEqual(result['schedule'][0]['start'], '2026-11-12T20:00:00+00:00')
            self.assertEqual(result['connection']['channel'], 'Garden Studio')
            self.assertIsNone(overview(root, now)['active'])
