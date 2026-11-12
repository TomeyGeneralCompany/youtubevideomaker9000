"""Decode the local writer's structured reply without recovering fragments."""
import json


def decode_script(reply):
    try:
        document = json.loads(reply)
    except json.JSONDecodeError as exc:
        raise ValueError(f'Qwen did not return a complete JSON document ({exc.msg}).') from exc
    if type(document) is not dict:
        raise ValueError('Qwen must return a single JSON object.')
    fields = ('title', 'description', 'script', 'mood', 'thumbnail_phrase', 'closing_script')
    for key in fields:
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise ValueError(f'Qwen reply needs a nonempty text field: {key}.')
    tags = document.get('tags')
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError('Qwen reply needs a list of text tags.')
    facts = document.get('facts')
    keys = ('source_id', 'claim', 'quote', 'value', 'period')
    if not isinstance(facts, list) or any(
        not isinstance(fact, dict) or any(not isinstance(fact.get(key), str) for key in keys)
        for fact in facts
    ):
        raise ValueError('Qwen reply needs a list of structured facts.')
    return document
