import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moduli import ai_client as ai
from moduli.quota_control import QuotaPaused


class LocalWriterTests(unittest.TestCase):
    def test_structured_writer_and_unload(self):
        messages = [{'role': 'user', 'content': 'Return JSON including closing_script'}]
        response = Mock()
        response.json.return_value = {'message': {'content': '<think>hidden</think>{"script":"hello"}'}}
        with patch.object(ai.requests, 'post', return_value=response) as post:
            self.assertEqual(ai._ollama_local(messages, 9000), '{"script":"hello"}')
        payload = post.call_args_list[0].kwargs['json']
        self.assertEqual(payload['model'], 'qwen3:4b')
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options']['num_predict'], 4096)
        self.assertEqual(payload['options']['num_ctx'], 8192)
        self.assertIn('closing_script', payload['format']['required'])
        self.assertIn('facts', payload['format']['required'])
        self.assertIn('/no_think', payload['messages'][-1]['content'])
        self.assertNotIn('/no_think', messages[-1]['content'])
        self.assertEqual(post.call_args_list[1].kwargs['json'], {'model': 'qwen3:4b', 'keep_alive': 0})

    def test_bad_output_is_rejected_and_model_unloaded(self):
        cases = [({'done_reason': 'length', 'message': {'content': 'partial'}}, 'truncated'),
                 ({'message': {'content': '<think>unfinished'}}, 'incomplete thinking'),
                 ({'message': {'content': ' '}}, 'no final answer')]
        for data, error in cases:
            with self.subTest(error=error):
                response = Mock()
                response.json.return_value = data
                with patch.object(ai.requests, 'post', return_value=response) as post:
                    with self.assertRaisesRegex(RuntimeError, error):
                        ai._ollama_local([], 100)
                self.assertEqual(post.call_count, 2)

    def test_script_schema_and_http_failure_unload(self):
        response = Mock()
        response.raise_for_status.side_effect = RuntimeError('offline')
        with patch.object(ai.requests, 'post', return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                ai._ollama_local([{'role': 'user', 'content': 'JSON with "script"'}], 512)
        self.assertEqual(post.call_args_list[0].kwargs['json']['format']['required'], ['script'])
        self.assertEqual(post.call_count, 2)

    def test_quota_uses_local_writer_directly(self):
        with patch.object(ai, '_primary', side_effect=QuotaPaused('cooldown')), \
             patch.object(ai, '_ollama_local', return_value='local answer') as local, \
             patch.object(ai, '_fallback') as fallback:
            self.assertEqual(ai.chat('test'), 'local answer')
            local.assert_called_once()
            fallback.assert_not_called()

    def test_primary_and_ordinary_fallback(self):
        with patch.object(ai, '_primary', return_value='primary answer'), patch.object(ai, '_ollama_local') as local:
            self.assertEqual(ai.chat('test'), 'primary answer')
            local.assert_not_called()
        with patch.object(ai, '_primary', side_effect=RuntimeError('offline')), \
             patch.object(ai, '_fallback', return_value='fallback answer'):
            self.assertEqual(ai.chat('test'), 'fallback answer')
