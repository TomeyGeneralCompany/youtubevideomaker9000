import json
import unittest
from unittest.mock import patch

from mavis.editorial_policy import review
from mavis.media_research import write_mascot_content
from mavis.patristic_sources import attach_sources, is_patristic, passages, validate_citations


class PatristicTests(unittest.TestCase):
    def test_writer_uses_primary_sources_offline(self):
        topic = 'Clement of Rome and Ignatius of Antioch on faith'
        self.assertTrue(is_patristic(topic))
        primary = passages(topic)
        self.assertEqual({p['author'] for p in primary}, {'Clement of Rome', 'Ignatius of Antioch'})
        closing = 'faith ' * 34 + 'alone'
        data = dict(title='Faith in the early church', description='A Reformed reading',
                    script='doctrine ' * 170 + closing, closing_script=closing,
                    mood='calm', thumbnail_phrase='Faith', tags=[], facts=[],
                    patristic_citations=[dict(source_id=p['source_id'], passage=p['passage'], quote='')
                                        for p in primary])
        with patch('mavis.ai_client.chat_ollama', return_value=json.dumps(data)) as writer:
            result = write_mascot_content(topic, {'sources': [], 'patristic': primary})
        self.assertIn('The early church was Reformed in doctrine from its beginnings', writer.call_args.args[0])
        self.assertIn('clement-corinthians-32', writer.call_args.args[0])
        self.assertTrue(writer.call_args.kwargs['patristic'])
        used = validate_citations(result, primary)
        attach_sources(result, used)
        attach_sources(result, used)
        self.assertEqual(result['description'].count('Primary passages:'), 1)

    def test_submitted_quote_and_fabrication(self):
        primary = passages('Ignatius and the Ephesians')
        self.assertEqual([p['source_id'] for p in primary], ['ignatius-ephesians-14'])
        content = {'script': 'Ignatius writes, “For the beginning is faith, and the end is love.”'}
        self.assertEqual(validate_citations(content, primary, infer=True), primary)
        content['script'] = 'Ignatius writes, “The moon is made of cheese.”'
        with self.assertRaisesRegex(ValueError, 'absent'):
            validate_citations(content, primary, infer=True)

    def test_reviewer_wiring(self):
        self.assertFalse(is_patristic('How to change a tire'))
        with patch('mavis.ai_client.chat_ollama', side_effect=['ALLOW', 'BLOCK']) as model:
            review({'script': 'A Reformed reading of Ignatius includes a quotation also cited by Orthodox writers.'})
            with self.assertRaisesRegex(ValueError, 'editorial policy'):
                review({'script': 'Convert to Eastern Orthodoxy.'})
        self.assertIn('not advocacy', model.call_args.kwargs['system'])
        self.assertIn('Eastern Orthodoxy', model.call_args.kwargs['system'])
