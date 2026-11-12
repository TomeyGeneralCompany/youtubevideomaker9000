from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paul_revere
from mavis import google_auth as auth


class YouTubeAuthTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.token = self.root / 'token.json'
        self.token.write_text('existing')
        self.client = Mock()
        self.client.channels.return_value.list.return_value.execute.return_value = {
            'items': [{'id': 'correct', 'snippet': {'title': 'MAVIS'}}]}
        self.cfg = {'expected_channel': 'MAVIS', 'expected_channel_id': 'correct'}
        self.enterContext(patch.object(paul_revere, 'ROOT', self.root))
        self.build = self.enterContext(patch.object(auth, 'build', return_value=self.client))
        self.saved = Mock(valid=True, refresh_token='saved-refresh')
        self.saved.to_json.return_value = 'refreshed'
        self.load = self.enterContext(patch.object(auth.Credentials, 'from_authorized_user_file', return_value=self.saved))
        self.browser = self.enterContext(patch.object(auth.InstalledAppFlow, 'from_client_secrets_file'))

    def test_saved_login_reuses_verified_client_without_rewriting_token(self):
        self.assertEqual(paul_revere.youtube_session(self.cfg), (self.client, 'correct'))
        self.load.assert_called_once_with(str(self.token))
        self.build.assert_called_once()
        self.browser.assert_not_called()
        self.saved.refresh.assert_not_called()
        self.assertEqual(self.token.read_text(), 'existing')

    def test_expired_login_refreshes_once_and_is_saved_privately(self):
        self.saved.valid = False
        self.saved.refresh.side_effect = lambda _: setattr(self.saved, 'valid', True)
        self.assertEqual(paul_revere.youtube_session(self.cfg)[1], 'correct')
        self.saved.refresh.assert_called_once()
        self.assertEqual(self.token.read_text(), 'refreshed')
        self.assertEqual(self.token.stat().st_mode & 0o777, 0o600)

    def test_unattended_rejected_refresh_never_opens_browser(self):
        self.saved.valid = False
        self.saved.refresh.side_effect = auth.RefreshError('revoked')
        with self.assertRaisesRegex(auth.AuthorizationRequired, 'authorize'):
            paul_revere.youtube_session(self.cfg)
        self.browser.assert_not_called()
        self.build.assert_not_called()
        self.assertEqual(self.token.read_text(), 'existing')

    def test_wrong_channel_is_rejected_and_cannot_replace_existing_token(self):
        (self.root / 'credentials.json').touch()
        self.browser.return_value.run_local_server.return_value = self.saved
        bad = {**self.cfg, 'expected_channel_id': 'another-channel'}
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            paul_revere.youtube_session(bad, authorize=True)
        self.assertEqual(self.token.read_text(), 'existing')
        self.assertEqual(paul_revere.youtube_session(self.cfg, authorize=True)[1], 'correct')
        self.assertEqual(self.token.read_text(), 'refreshed')
