import array, hashlib, importlib, json, os, sys, tempfile, unittest, wave
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from moduli import preferenze, audio, shorts, local_voice
from PIL import Image

class ConversionTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = Path.cwd()
        os.chdir(self.root)
        self.env = patch.dict(os.environ, {'TUBE_WORKSPACE': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_english_preferences_and_legacy_values(self):
        (self.root / 'video-preferences.json').write_text(json.dumps({'ritmo': 'veloce', 'thumbnail_testo_posizione': 'alto'}))
        p = preferenze.load_preferences()
        self.assertEqual(p['pacing'], 'fast')
        self.assertEqual(p['thumbnail_text_position'], 'top')
        self.assertNotIn('ritmo', p)
        self.assertEqual(preferenze.update_from_text('set pacing to slow')['pacing'], 'slow')
        self.assertFalse(preferenze.update_from_text('hide thumbnail text')['thumbnail_show_text'])
        self.assertEqual(preferenze.update_from_text('put text at the top')['thumbnail_text_position'], 'top')
        self.assertIn('Current video preferences', preferenze.format_preferences_html())
        self.assertEqual(preferenze.update_from_text('what is the current language?'), {})

    def test_no_default_speaker(self):
        with self.assertRaisesRegex(RuntimeError, 'Select a voice profile'):
            audio._load_voice()
        (self.root / 'voice-profile.json').write_text(json.dumps({'provider': 'edge-tts', 'voice': 'explicit-test-voice'}))
        self.assertEqual(audio._load_voice(), 'explicit-test-voice')

    def test_local_voice_pipeline_uses_selected_profile_and_cache(self):
        local_voice.ROOT = self.root
        (self.root / 'voice-profile.json').write_text(json.dumps({'provider': 'qwen-local', 'instruction': 'Test voice instruction', 'reference_text': 'Test reference transcript', 'seed': 3}))
        calls = []

        def engine(command, text):
            calls.append((command, text))
            dest = Path(command[command.index('-o') + 1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(dest), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(array.array('h', [1000, -1000] * 12000).tobytes())
        with patch.object(local_voice, 'run', engine):
            local_voice.synthesize('Example narration.', self.root / 'one.mp3')
            local_voice.synthesize('Example narration.', self.root / 'two.mp3')
        self.assertEqual(len(calls), 2)
        self.assertIn('Test voice instruction', calls[0][0])
        self.assertEqual(calls[1][1], 'Example narration.')
        self.assertTrue((self.root / 'one.mp3').stat().st_size > 1024)

    def test_complete_cel_pipeline_accepts_new_artwork(self):
        assets = self.root / 'assets/animation'
        assets.mkdir(parents=True)
        for name, size in [('poses.png', (96, 64)), ('walk-cycle.png', (128, 64)), ('puff-cycle.png', (96, 32))]:
            Image.new('RGBA', size, (70, 100, 130, 255)).save(assets / name)
        (assets / 'walk-cycle.json').write_text(json.dumps([{'mouth': [16, 12], 'floor': 30}] * 8))
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in assets.iterdir()}
        (assets / 'approved-animation-sha256.json').write_text(json.dumps(manifest))
        sys.modules.pop('moduli.mascot', None)
        mascot = importlib.import_module('moduli.mascot')
        self.assertEqual(len(mascot.load_poses(size=60)), 6)
        frame = mascot.frame_at(mascot.stage('Test headline'), mascot.load_poses(size=60), 1, 0.5)
        self.assertEqual(frame.size, (1080, 1920))
        action = mascot.frame_at(mascot.stage('Test headline'), mascot.load_poses(size=60), 75.5, 0.5)
        self.assertEqual(action.size, (1080, 1920))
        from paul_revere_animation_guard import verify_approved_animation
        verify_approved_animation()
        (assets / 'poses.png').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'failed verification'):
            verify_approved_animation()

    def test_caption_identity_is_configurable(self):
        (self.root / 'media-profile.json').write_text(json.dumps({'brand_name': 'Example Brand'}))
        path = self.root / 'captions.ass'
        shorts.write_ass('English narration example', path)
        text = path.read_text()
        self.assertIn('Example Brand', text)
        self.assertNotIn('PAUL REVERE MEDIA', text)

    def test_audio_chunking_retains_all_words(self):
        words = ['sample'] * 901
        chunks = audio._split_chunks(' '.join(words))
        self.assertTrue(all((len(c.split()) <= 300 for c in chunks)))
        self.assertEqual(sum((len(c.split()) for c in chunks)), 901)
if __name__ == '__main__':
    unittest.main()
