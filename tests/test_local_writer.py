import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mavis import ai_client as ai


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
        self.assertIn('language', payload['format']['required'])
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

    def test_public_writer_ignores_old_cloud_provider_setting(self):
        response = Mock()
        response.json.return_value = {'message': {'content': 'local answer'}}
        with patch.dict(os.environ, {'AI_SERVICE': 'openrouter'}), \
             patch.object(ai.requests, 'post', return_value=response) as post:
            self.assertEqual(ai.chat_ollama('test', system='system test'), 'local answer')
        self.assertEqual([call.args[0] for call in post.call_args_list], [
            'http://localhost:11434/api/chat', 'http://127.0.0.1:11434/api/generate',
        ])
        self.assertEqual(post.call_args_list[0].kwargs['json']['messages'][0],
                         {'role': 'system', 'content': 'system test'})
